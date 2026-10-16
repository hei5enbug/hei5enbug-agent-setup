#!/usr/bin/env python3
"""Run a command with protected values in its environment and mask them in its output.

Usage:
  python3 scripts/secret_exec.py (--secret VAR=SOURCE | --file VAR=SOURCE)... [--timeout N] -- COMMAND [ARG...]

--secret sets VAR to the value. --file writes the value to a new 0600 file in a private 0700 temporary directory and
sets VAR to that file's path. The directory is removed when the helper exits, including on error or signal. Sources are
fetched by running their CLI without a shell. Values are never printed, logged, or placed in an argv.

Sources:
  k8s:[<context>/]<namespace>/<secret>/<key>   Kubernetes Secret key, base64-decoded
  keyvault:<vault>/<name>                       Azure Key Vault secret, one trailing newline removed
  aws:<secret id>[#<json key>]                  AWS Secrets Manager string, or one string field of its JSON
  gcp:<project>/<name>[/<version>]              Google Secret Manager payload, version defaults to latest

COMMAND runs as an argv list without a shell and inherits stdin. Its stdout and stderr are masked: every value and its
base64 and URL-quoted forms become ***. Exit codes: the command's code (128+signal when killed), 124 on timeout,
127 when the command is not found, 2 for usage or fetch errors.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from dataclasses import dataclass
from functools import partial
from typing import Callable

sys.dont_write_bytecode = True

EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_CANNOT_RUN = 126
EXIT_NOT_FOUND = 127
EXIT_TIMEOUT = 124
MASK = b"***"
READ_SIZE = 65536
VAR_PATTERN = re.compile(r"[A-Z_][A-Z0-9_]*")
USAGE = "usage: secret_exec.py (--secret VAR=SOURCE | --file VAR=SOURCE)... [--timeout N] -- COMMAND [ARG...]"

Decoder = Callable[[bytes], bytes]


class UsageError(Exception):
    pass


class FetchError(Exception):
    def __init__(self, source: str, reason: str):
        super().__init__(reason)
        self.source = source
        self.reason = reason


class Interrupted(BaseException):
    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


class Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise UsageError(message)


@dataclass(frozen=True)
class FetchSpec:
    source: str
    argv: list[str]
    decode: Decoder


@dataclass(frozen=True)
class Binding:
    name: str
    spec: FetchSpec
    as_file: bool


@dataclass(frozen=True)
class Plan:
    bindings: list[Binding]
    command: list[str]
    timeout: float | None


def report(message: str) -> None:
    sys.stderr.write(f"secret_exec: {message}\n")
    sys.stderr.flush()


def masked_forms(value: bytes) -> set[bytes]:
    quoted = (
        urllib.parse.quote_from_bytes(value),
        urllib.parse.quote_from_bytes(value, safe=""),
        urllib.parse.quote_plus(value),
    )
    return {value, base64.b64encode(value), *(text.encode("ascii") for text in quoted)}


class OutputMasker:
    """Replace every occurrence of the masked forms in a stream, including occurrences split across chunks."""

    def __init__(self, values: list[bytes]):
        forms = {form for value in values for form in masked_forms(value)}
        self._forms = sorted(forms)
        self._hold = max((len(form) for form in forms), default=1) - 1
        self._pending = b""

    def feed(self, chunk: bytes) -> bytes:
        return self._emit(self._pending + chunk, final=False)

    def finish(self) -> bytes:
        return self._emit(self._pending, final=True)

    def _emit(self, data: bytes, *, final: bool) -> bytes:
        spans = self._spans(data)
        # Keep the last hold bytes unemitted: a form that is still incomplete can only start there.
        limit = len(data) if final else max(0, len(data) - self._hold)
        for start, end in spans:
            if start < limit < end:
                limit = start
        output = []
        position = 0
        for start, end in spans:
            if end > limit:
                break
            output += [data[position:start], MASK]
            position = end
        output.append(data[position:limit])
        self._pending = data[limit:]
        return b"".join(output)

    def _spans(self, data: bytes) -> list[tuple[int, int]]:
        found = []
        for form in self._forms:
            index = data.find(form)
            while index != -1:
                found.append((index, index + len(form)))
                index = data.find(form, index + 1)
        merged: list[tuple[int, int]] = []
        for start, end in sorted(found):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged


def mask_bytes(data: bytes, values: list[bytes]) -> bytes:
    masker = OutputMasker(values)
    return masker.feed(data) + masker.finish()


def strip_one_newline(data: bytes) -> bytes:
    return data[:-1] if data.endswith(b"\n") else data


def identity(data: bytes) -> bytes:
    return data


def decode_base64(data: bytes) -> bytes:
    try:
        return base64.b64decode(data.strip(), validate=True)
    except ValueError:
        raise ValueError("the value is not valid base64") from None


def json_string_field(key: str, data: bytes) -> bytes:
    try:
        payload = json.loads(data)
    except ValueError:
        raise ValueError("the SecretString is not JSON") from None
    if not isinstance(payload, dict) or not isinstance(payload.get(key), str):
        raise ValueError("the JSON key is missing or is not a string")
    try:
        return payload[key].encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("the JSON string is not valid UTF-8") from None


def build_k8s(rest: str) -> tuple[list[str], Decoder]:
    pieces = rest.split("/")
    if len(pieces) < 3 or not all(pieces):
        raise ValueError("expected [context/]namespace/secret/key")
    *context, namespace, secret, key = pieces
    argv = ["kubectl"]
    if context:
        argv += ["--context", "/".join(context)]
    jsonpath = "{.data." + key.replace(".", r"\.") + "}"
    argv += ["-n", namespace, "get", "secret", secret, "-o", f"jsonpath={jsonpath}"]
    return argv, decode_base64


def build_keyvault(rest: str) -> tuple[list[str], Decoder]:
    parts = rest.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError("expected vault/name")
    vault, name = parts
    argv = ["az", "keyvault", "secret", "show", "--vault-name", vault, "--name", name, "--query", "value", "-o", "tsv"]
    return argv, strip_one_newline


def build_aws(rest: str) -> tuple[list[str], Decoder]:
    secret_id, marker, json_key = rest.partition("#")
    if not secret_id or (marker and not json_key):
        raise ValueError("expected secret-id[#json-key]")
    argv = ["aws", "secretsmanager", "get-secret-value", "--secret-id", secret_id]
    argv += ["--query", "SecretString", "--output", "text"]
    if not marker:
        return argv, strip_one_newline
    return argv, partial(json_string_field, json_key)


def build_gcp(rest: str) -> tuple[list[str], Decoder]:
    parts = rest.split("/")
    if len(parts) not in (2, 3) or not all(parts):
        raise ValueError("expected project/name[/version]")
    project, name, *version = parts
    argv = ["gcloud", "secrets", "versions", "access", version[0] if version else "latest"]
    return [*argv, "--secret", name, "--project", project], identity


BUILDERS = {"k8s": build_k8s, "keyvault": build_keyvault, "aws": build_aws, "gcp": build_gcp}


def parse_source(name: str, source: str) -> FetchSpec:
    kind, separator, rest = source.partition(":")
    builder = BUILDERS.get(kind) if separator else None
    if builder is None:
        raise UsageError(f"{name} source must start with k8s:, keyvault:, aws:, or gcp:")
    try:
        argv, decode = builder(rest)
    except ValueError as error:
        raise UsageError(f"{name} source is malformed: {error}") from None
    return FetchSpec(source, argv, decode)


def parse_binding(text: str, *, as_file: bool) -> Binding:
    name, separator, source = text.partition("=")
    if not separator or not VAR_PATTERN.fullmatch(name):
        flag = "--file" if as_file else "--secret"
        raise UsageError(f"{flag} expects VAR=SOURCE with VAR matching [A-Z_][A-Z0-9_]*")
    return Binding(name, parse_source(name, source), as_file)


def positive_seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("--timeout expects a number of seconds") from None
    if not 0 < value < math.inf:
        raise argparse.ArgumentTypeError("--timeout expects a positive number of seconds")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="secret_exec.py", add_help=False)
    parser.add_argument("--secret", action="append", default=[], metavar="VAR=SOURCE")
    parser.add_argument("--file", dest="files", action="append", default=[], metavar="VAR=SOURCE")
    parser.add_argument("--timeout", type=positive_seconds)
    return parser


def parse_arguments(argv: list[str]) -> Plan:
    if "--" not in argv:
        raise UsageError("COMMAND must follow --")
    divider = argv.index("--")
    options = build_parser().parse_args(argv[:divider])
    command = argv[divider + 1:]
    if not command:
        raise UsageError("COMMAND is required after --")
    bindings = [parse_binding(text, as_file=False) for text in options.secret]
    bindings += [parse_binding(text, as_file=True) for text in options.files]
    if not bindings:
        raise UsageError(
            "at least one --secret or --file is required; run a command that needs no protected value directly"
        )
    names = [binding.name for binding in bindings]
    if len(set(names)) != len(names):
        raise UsageError("each VAR may be bound only once")
    return Plan(bindings, command, options.timeout)


def fetch(spec: FetchSpec) -> bytes:
    try:
        completed = subprocess.run(spec.argv, stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=30)
    except subprocess.TimeoutExpired:
        raise FetchError(spec.source, f"{spec.argv[0]} timed out") from None
    except OSError:
        raise FetchError(spec.source, f"cannot run {spec.argv[0]}") from None
    if completed.returncode != 0:
        reason = f"{spec.argv[0]} exited with code {completed.returncode}"
        raise FetchError(spec.source, reason)
    try:
        value = spec.decode(completed.stdout)
    except ValueError as error:
        raise FetchError(spec.source, str(error)) from None
    if not value:
        raise FetchError(spec.source, "the value is empty")
    return value


def stop_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def pump(stream, sink, masker: OutputMasker) -> None:
    with stream:
        while True:
            chunk = stream.read1(READ_SIZE)
            if not chunk:
                break
            sink.write(masker.feed(chunk))
            sink.flush()
        sink.write(masker.finish())
        sink.flush()


def wait_for_child(process: subprocess.Popen, timeout: float | None) -> int:
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop_group(process)
        return EXIT_TIMEOUT
    except Interrupted:
        stop_group(process)
        raise
    return 128 - returncode if returncode < 0 else returncode


def run_command(command: list[str], environment: dict[str, str], timeout: float | None, values: list[bytes]) -> int:
    try:
        process = subprocess.Popen(
            command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
    except FileNotFoundError:
        report(f"command not found: {command[0]}")
        return EXIT_NOT_FOUND
    except OSError:
        report(f"cannot run command: {command[0]}")
        return EXIT_CANNOT_RUN
    pumps = [
        threading.Thread(target=pump, args=(process.stdout, sys.stdout.buffer, OutputMasker(values)), daemon=True),
        threading.Thread(target=pump, args=(process.stderr, sys.stderr.buffer, OutputMasker(values)), daemon=True),
    ]
    for thread in pumps:
        thread.start()
    try:
        return wait_for_child(process, timeout)
    finally:
        for thread in pumps:
            thread.join()


def execute(plan: Plan) -> int:
    values: list[bytes] = []
    resolved: list[tuple[Binding, bytes]] = []
    try:
        for binding in plan.bindings:
            value = fetch(binding.spec)
            if not binding.as_file and b"\0" in value:
                raise FetchError(binding.spec.source, "the value contains a NUL byte; use --file")
            values.append(value)
            resolved.append((binding, value))
    except FetchError as error:
        report(f"cannot fetch {error.source}: {error.reason}")
        return EXIT_USAGE

    temp_dir: str | None = None
    try:
        environment = dict(os.environ)
        for binding, value in resolved:
            if not binding.as_file:
                environment[binding.name] = os.fsdecode(value)
                continue
            if temp_dir is None:
                temp_dir = tempfile.mkdtemp(prefix="secret_exec-")
            path = os.path.join(temp_dir, binding.name)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(value)
            environment[binding.name] = path
        return run_command(plan.command, environment, plan.timeout, values)
    except OSError as error:
        report(f"cannot write a temporary file: {error.strerror}")
        return EXIT_FAILURE
    finally:
        if temp_dir is not None:
            ignore_signals()
            shutil.rmtree(temp_dir, ignore_errors=True)


def raise_interrupted(signum: int, frame) -> None:
    raise Interrupted(signum)


HANDLED_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def install_signal_handlers() -> None:
    for signum in HANDLED_SIGNALS:
        signal.signal(signum, raise_interrupted)


def ignore_signals() -> None:
    """Keep the temporary directory cleanup from being cut short by a second signal."""
    for signum in HANDLED_SIGNALS:
        signal.signal(signum, signal.SIG_IGN)


def main(argv: list[str] | None = None) -> int:
    install_signal_handlers()
    try:
        return execute(parse_arguments(sys.argv[1:] if argv is None else argv))
    except UsageError as error:
        report(f"usage error: {error}")
        report(USAGE)
        return EXIT_USAGE
    except Interrupted as interrupted:
        return 128 + interrupted.signum


if __name__ == "__main__":
    raise SystemExit(main())
