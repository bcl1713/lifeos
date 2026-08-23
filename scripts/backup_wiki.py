#!/usr/bin/env python3
"""Create a regular-file tar backup of a canonical LifeOS wiki root."""

from __future__ import annotations

import argparse
from pathlib import Path

from lifeos.backups import backup_wiki


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(f"backup={backup_wiki(args.wiki_root, args.output)}")


if __name__ == "__main__":
    main()