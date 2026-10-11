"""Reject tracked local environment files; allow documented example templates only."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import PurePosixPath
from typing import Iterable


def is_disallowed_environment_file(path: str) -> bool:
    """Return true for tracked .env files other than .example templates."""
    name = PurePosixPath(path).name
    if name == ".env":
        return True
    if name.startswith(".env.") and not name.endswith(".example"):
        return True
    return False


def find_disallowed_paths(paths: Iterable[str]) -> list[str]:
    """Return unsafe tracked paths in deterministic order."""
    return sorted(path for path in paths if path and is_disallowed_environment_file(path))


def tracked_paths_from_git() -> list[str]:
    """Read Git's NUL-delimited path list safely, including names containing newlines."""
    raw = subprocess.check_output(["git", "ls-files", "-z")
    return [os.fsdecode(path) for path in raw.split(b"\0") if path]


def main() -> int:
    try:
        paths = tracked_paths_from_git()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Could not inspect tracked files: {exc}", file=sys.stderr)
        return 2

    disallowed = find_disallowed_paths(paths)
    if disallowed:
        print("Refusing tracked local environment/secret files:")
        for path in disallowed:
            print(f"  - {path}")
        print("Use an untracked local .env file and commit only .example templates.")
        return 1

    print("Tracked environment-file check passed; only documented .example templates are permitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
