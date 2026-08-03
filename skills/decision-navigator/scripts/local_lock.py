#!/usr/bin/env python3

import argparse
import datetime as dt
import json
import os
import re
import socket
import sys
from pathlib import Path


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def resolve_resource(value: str) -> tuple[Path, Path]:
    raw = Path(value).expanduser()
    if raw.is_symlink():
        fail("Resource must not be a symlink")
    try:
        resource = raw.resolve(strict=True)
    except FileNotFoundError:
        fail(f"Resource not found: {raw}")
    if not resource.is_file():
        fail(f"Resource is not a file: {resource}")

    if resource.name == "map.md":
        effort = resource.parent
        key = "map"
    elif resource.parent.name == "tickets":
        effort = resource.parent.parent
        key = resource.stem
    else:
        fail("Resource must be map.md or a file directly under tickets/")

    if effort.parent.name != ".decision-navigator":
        fail("Resource must belong to .decision-navigator/<effort>/")

    claims = effort / "claims"
    if claims.is_symlink():
        fail("Claims directory must not be a symlink")
    claims.mkdir(parents=True, exist_ok=True)
    return resource, claims / f"{key}.lock"


def ticket_status(resource: Path) -> str | None:
    if resource.name == "map.md":
        return None
    match = re.search(r"^Status:\s*([^\s]+)\s*$", resource.read_text(), re.MULTILINE)
    if not match:
        fail(f"Ticket has no valid Status field: {resource}")
    return match.group(1)


def read_metadata(lock: Path) -> dict:
    metadata_path = lock / "claim.json"
    if not metadata_path.is_file():
        return {}
    try:
        return json.loads(metadata_path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        fail(f"Invalid claim metadata at {metadata_path}: {error}")


def claim(resource: Path, lock: Path, owner: str | None) -> None:
    if not owner:
        fail("claim requires --owner")
    status = ticket_status(resource)
    if status is not None and status != "open":
        fail(f"Ticket is not open: {resource} has Status: {status}")

    try:
        os.mkdir(lock)
    except FileExistsError:
        if lock.is_symlink() or not lock.is_dir():
            fail(f"Unsafe lock path: {lock}")
        metadata = read_metadata(lock)
        holder = metadata.get("owner", "unknown")
        fail(f"Resource already claimed by {holder}: {resource}")

    payload = {
        "owner": owner,
        "resource": str(resource),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
    }
    try:
        (lock / "claim.json").write_text(json.dumps(payload, indent=2) + "\n")
    except OSError:
        os.rmdir(lock)
        raise
    print(json.dumps({"claimed": True, "lock": str(lock), **payload}))


def inspect(resource: Path, lock: Path) -> None:
    if not lock.exists():
        print(json.dumps({"claimed": False, "resource": str(resource)}))
        return
    if not lock.is_dir() or lock.is_symlink():
        fail(f"Unsafe lock path: {lock}")
    print(json.dumps({"claimed": True, "lock": str(lock), **read_metadata(lock)}))


def release(resource: Path, lock: Path, owner: str | None, force: bool) -> None:
    if not lock.is_dir() or lock.is_symlink():
        fail(f"Lock not found or unsafe: {lock}")
    metadata = read_metadata(lock)
    holder = metadata.get("owner")
    if not force:
        if not owner:
            fail("release requires --owner unless --force is used")
        if holder != owner:
            fail(f"Claim belongs to {holder or 'unknown'}, not {owner}")

    entries = list(lock.iterdir())
    unexpected = [entry for entry in entries if entry.name != "claim.json"]
    if unexpected:
        fail(f"Lock contains unexpected files: {lock}")
    metadata_path = lock / "claim.json"
    if metadata_path.exists():
        metadata_path.unlink()
    lock.rmdir()
    print(json.dumps({"released": True, "resource": str(resource), "lock": str(lock)}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("claim", "inspect", "release"))
    parser.add_argument("resource")
    parser.add_argument("--owner")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    resource, lock = resolve_resource(args.resource)
    if args.action == "claim":
        claim(resource, lock, args.owner)
    elif args.action == "inspect":
        inspect(resource, lock)
    else:
        release(resource, lock, args.owner, args.force)


if __name__ == "__main__":
    main()
