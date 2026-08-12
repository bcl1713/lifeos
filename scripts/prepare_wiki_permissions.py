#!/usr/bin/env python3
"""Prepare the narrow LifeOS wiki subtree without following symlinks."""

from __future__ import annotations

import argparse
import os
import pwd
import sys
from pathlib import Path

_COMPONENTS = ("01-Projects", "LifeOS", "lifeos")
_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def prepare(wiki_root: Path, supplementary_gid: int | None) -> None:
    """Open/create each component safely, then update only the final directory."""
    fds: list[int] = []
    try:
        current_fd = os.open(wiki_root, _OPEN_FLAGS)
        fds.append(current_fd)
        for component in _COMPONENTS:
            parent_stat = os.fstat(current_fd)
            try:
                child_fd = os.open(component, _OPEN_FLAGS, dir_fd=current_fd)
            except FileNotFoundError:
                os.mkdir(component, 0o755, dir_fd=current_fd)
                child_fd = os.open(component, _OPEN_FLAGS, dir_fd=current_fd)
                os.fchown(child_fd, parent_stat.st_uid, parent_stat.st_gid)
            fds.append(child_fd)
            current_fd = child_fd

        if supplementary_gid is not None:
            os.fchown(current_fd, -1, supplementary_gid)
            os.fchmod(current_fd, 0o2775)
        else:
            lifeos = pwd.getpwnam("lifeos")
            os.fchown(current_fd, lifeos.pw_uid, lifeos.pw_gid)
            os.fchmod(current_fd, 0o755)
    finally:
        for fd in reversed(fds):
            os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki-root", type=Path, default=Path("/wiki"))
    parser.add_argument("--supplementary-gid", type=int)
    args = parser.parse_args()
    try:
        prepare(args.wiki_root, args.supplementary_gid)
    except (OSError, KeyError) as exc:
        print(f"refusing unsafe canonical wiki path: {exc}", file=sys.stderr)
        return 64
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
