"""Two harder researcher cases of the GPT role comparison. Each asks for several precise facts that official documentation states and a
guess gets wrong, and the grader checks the facts, an official URL, and a web search call in the rollout.

R2: the Node.js versions that enable type stripping by default and the version that added --experimental-transform-types (nodejs.org
TypeScript page history table, read 2026-11-20: enabled by default in v23.6.0 and v22.18.0, transform-types added in v22.7.0).
R3: the PostgreSQL versions that added MERGE and MERGE ... RETURNING, and the function that names the action of a returned row
(PostgreSQL 15 and 17 release notes, MERGE reference page, read 2026-11-20: 15, 17, merge_action())."""

from __future__ import annotations

import re

ASSIGNMENTS = {
    "R2": (
        "Use only the web search tool. In the official Node.js documentation, find: (a) the first Node.js version of the v23 line in which "
        "TypeScript type stripping is enabled by default, (b) the version of the v22 line to which that change was backported, and (c) the Node.js "
        "version in which the --experimental-transform-types flag was added. Answer each with its exact version and give the URL of each official page you used. Change no file.\n"),
    "R3": (
        "Use only the web search tool. In the official PostgreSQL documentation, find: (a) the major version that added the MERGE command, "
        "(b) the first major version in which MERGE accepts a RETURNING clause, and (c) the exact name of the function that reports which action "
        "produced each row MERGE returns. Answer each with its exact value and give the URL of each official page you used. Change no file.\n"),
}
WEB_SEARCH = re.compile(r"web_search|web\.search|tools\.web__run")
URL_HOSTS = {"R2": r"https?://(?:[\w-]+\.)*nodejs\.org/\S*", "R3": r"https?://(?:[\w-]+\.)*postgresql\.org/\S*"}


def near(first: str, second: str) -> re.Pattern:
    """The two patterns within one sentence of each other, in either order."""
    return re.compile(rf"(?is){first}[^.\n]{{0,120}}{second}|{second}[^.\n]{{0,120}}{first}")


def version(number: str) -> str:
    return rf"(?<![\d.]){re.escape(number)}(?!\d)"


def facts_failures(case_id: str, answer: str) -> list[str]:
    found = []
    if case_id == "R2":
        for number in ("23.6.0", "22.18.0"):
            if not re.search(version(number), answer):
                found.append(f"the version {number} is missing")
        if not near(r"transform-types", version("22.7.0")).search(answer):
            found.append("--experimental-transform-types is not tied to v22.7.0")
    else:
        if not near(r"MERGE", version("15")).search(answer):
            found.append("MERGE is not tied to version 15")
        if not near(r"RETURNING", version("17")).search(answer):
            found.append("RETURNING is not tied to version 17")
        if "merge_action" not in answer:
            found.append("the function merge_action is missing")
    return found


def failures(case_id: str, answer: str, records: str) -> list[str]:
    found = facts_failures(case_id, answer)
    if not re.search(URL_HOSTS[case_id], answer):
        found.append("no URL of the official site")
    if not WEB_SEARCH.search(records):
        found.append("the rollout shows no web search call")
    return found
