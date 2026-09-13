"""Reject Cyrillic characters in tracked files and commit messages."""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
import unicodedata
from pathlib import Path


def contains_cyrillic(data: bytes) -> bool:
    """Return whether UTF-8 text contains a Cyrillic character."""
    if b"\0" in data:
        return False
    return any(
        "CYRILLIC" in unicodedata.name(character, "")
        for character in data.decode("utf-8", errors="ignore")
    )


def archive_contains_cyrillic(data: bytes) -> bool:
    """Inspect text members of a compressed collection artifact."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    if contains_cyrillic(member.name.encode()):
                        return True
                    continue
                if contains_cyrillic(member.name.encode()):
                    return True
                file_obj = archive.extractfile(member)
                if file_obj is not None and contains_cyrillic(file_obj.read()):
                    return True
    except tarfile.TarError:
        return contains_cyrillic(data)
    return False


def content_contains_cyrillic(path: str, data: bytes) -> bool:
    """Check ordinary text and archive content, based on the path suffix."""
    if path.endswith(".tar.gz"):
        return archive_contains_cyrillic(data)
    return contains_cyrillic(data)


def tracked_paths() -> list[str]:
    """Return paths currently tracked in the working tree."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [path for path in result.stdout.decode().split("\0") if path]


def staged_paths() -> list[str]:
    """Return paths present in the Git index."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [path for path in result.stdout.decode().split("\0") if path]


def staged_content(path: str) -> bytes:
    """Read a path from the Git index."""
    result = subprocess.run(
        ["git", "show", f":{path}"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout


def check_paths(paths: list[str], staged: bool) -> list[str]:
    violations: list[str] = []
    for path in paths:
        try:
            data = staged_content(path) if staged else Path(path).read_bytes()
        except FileNotFoundError:
            continue
        if contains_cyrillic(path.encode()) or content_contains_cyrillic(path, data):
            violations.append(path)
    return violations


def check_message(path: str) -> list[str]:
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return []
    return [path] if contains_cyrillic(data) else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="check content in the Git index")
    mode.add_argument("--message", metavar="PATH", help="check a commit message file")
    args = parser.parse_args()

    if args.message:
        violations = check_message(args.message)
    else:
        paths = staged_paths() if args.staged else tracked_paths()
        violations = check_paths(paths, staged=args.staged)

    if violations:
        print("Cyrillic characters found in:", file=sys.stderr)
        print("\n".join(violations), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
