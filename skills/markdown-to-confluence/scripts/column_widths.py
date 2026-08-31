#!/usr/bin/env python3
"""Estimate table column widths that sum to a requested integer total.

Input is a JSON array with one array of cell strings per column. Output is JSON containing one
integer width per column. Content weighting is a deterministic estimate, not visual validation.

Image columns require an explicit ``--floor INDEX=PIXELS`` because image dimensions cannot be
recovered reliably from Markdown text. Impossible floor totals and invalid numeric options fail.

Exit codes: 0 widths computed, 2 invalid or unsupported input.
"""

import argparse
import json
import math
import re
import sys

IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINE_SPLIT_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
WIDE_CHAR_FLOOR = 0x2E80


class InputError(ValueError):
    pass


def visual_length(text, wide, narrow):
    return sum(wide if ord(character) >= WIDE_CHAR_FLOOR else narrow for character in text)


def longest_line(cell, wide, narrow):
    stripped = IMAGE_PATTERN.sub("", cell)
    longest = 0.0
    for line in LINE_SPLIT_PATTERN.split(stripped):
        code_spans = line.count("`") // 2
        text = line.replace("`", "").replace("**", "").strip()
        length = visual_length(text, wide, narrow) + code_spans * narrow * 2
        longest = max(longest, length)
    return longest


def has_image(cells):
    return any(IMAGE_PATTERN.search(cell) for cell in cells)


def distribute_with_caps(amount, weights, capacities):
    allocation = [0.0] * len(weights)
    active = {index for index, capacity in enumerate(capacities) if capacity > 0}

    while amount > 1e-9 and active:
        weight_sum = sum(weights[index] for index in active)
        saturated = []
        for index in sorted(active):
            share = amount * weights[index] / weight_sum
            if share >= capacities[index] - allocation[index] - 1e-9:
                saturated.append(index)
        if not saturated:
            for index in sorted(active):
                allocation[index] += amount * weights[index] / weight_sum
            amount = 0.0
            break
        for index in saturated:
            grant = capacities[index] - allocation[index]
            allocation[index] += grant
            amount -= grant
            active.remove(index)

    return allocation, amount


def round_to_total(values, total):
    rounded = [math.floor(value) for value in values]
    remainder = total - sum(rounded)
    order = sorted(
        range(len(values)),
        key=lambda index: (values[index] - rounded[index], -index),
        reverse=True,
    )
    for index in order[:remainder]:
        rounded[index] += 1
    return rounded


def column_widths(columns, options):
    weights = []
    floors = []
    caps = []

    for index, cells in enumerate(columns):
        if has_image(cells) and index not in options.floors:
            raise InputError("image column {} requires an explicit --floor".format(index))

        lengths = [longest_line(cell, options.wide_char, options.narrow_char) for cell in cells]
        longest = max(lengths) if lengths else 0.0
        average = sum(lengths) / len(lengths) if lengths else 0.0
        header = lengths[0] if lengths else 0.0

        needed = math.ceil(longest * options.char_width + options.padding)
        floor = math.ceil(max(options.min_width, header * options.char_width + options.padding))
        if index in options.floors:
            floor = max(floor, options.floors[index])

        weights.append(max(0.45 * longest + 0.55 * average, 3.0))
        floors.append(floor)
        caps.append(max(needed, floor))

    floor_total = sum(floors)
    if floor_total > options.total:
        raise InputError(
            "column floors total {} but --total is {}".format(floor_total, options.total)
        )

    remaining = options.total - floor_total
    capacities = [cap - floor for cap, floor in zip(caps, floors)]
    capped, remaining = distribute_with_caps(remaining, weights, capacities)
    values = [floor + extra for floor, extra in zip(floors, capped)]

    if remaining > 1e-9:
        weight_sum = sum(weights)
        values = [
            value + remaining * weight / weight_sum
            for value, weight in zip(values, weights)
        ]

    rounded = round_to_total(values, options.total)
    detail = [
        {
            "index": index,
            "header": columns[index][0] if columns[index] else "",
            "needed": caps[index],
            "floor": floors[index],
            "width": rounded[index],
        }
        for index in range(len(rounded))
    ]
    return rounded, detail


def parse_floor(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError("--floor takes INDEX=PIXELS")
    index_text, pixels_text = value.split("=", 1)
    try:
        index = int(index_text)
        pixels = int(pixels_text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--floor takes whole numbers") from error
    if pixels < 0:
        raise argparse.ArgumentTypeError("--floor pixels cannot be negative")
    return index, pixels


def fail(message):
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2))
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--columns", required=True, help="JSON file or - for standard input")
    parser.add_argument("--total", type=int, default=1800)
    parser.add_argument("--char-width", type=float, default=17.0)
    parser.add_argument("--padding", type=int, default=46)
    parser.add_argument("--min-width", type=int, default=110)
    parser.add_argument("--wide-char", type=float, default=1.0)
    parser.add_argument("--narrow-char", type=float, default=0.5)
    parser.add_argument("--floor", type=parse_floor, action="append", default=[])
    options = parser.parse_args(argv)
    options.floors = dict(options.floor)

    if options.total <= 0:
        return fail("--total must be positive")
    if options.char_width <= 0 or options.wide_char <= 0 or options.narrow_char <= 0:
        return fail("character widths must be positive")
    if options.padding < 0 or options.min_width < 0:
        return fail("--padding and --min-width cannot be negative")

    try:
        if options.columns == "-":
            raw = sys.stdin.read()
        else:
            with open(options.columns, encoding="utf-8") as handle:
                raw = handle.read()
        columns = json.loads(raw)
    except OSError as error:
        return fail("cannot read {}: {}".format(options.columns, error))
    except ValueError as error:
        return fail("input is not valid JSON: {}".format(error))

    if not isinstance(columns, list) or not columns:
        return fail("input must be a non-empty array of columns")
    for column in columns:
        if not isinstance(column, list) or not all(isinstance(cell, str) for cell in column):
            return fail("every column must be an array of strings")
    for index in options.floors:
        if index < 0 or index >= len(columns):
            return fail("--floor index {} is outside the input".format(index))

    try:
        widths, detail = column_widths(columns, options)
    except InputError as error:
        return fail(str(error))

    print(
        json.dumps(
            {"ok": True, "total": sum(widths), "widths": widths, "columns": detail},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
