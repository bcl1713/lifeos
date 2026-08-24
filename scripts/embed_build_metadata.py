#!/usr/bin/env python3
"""Embed immutable artifact identity into the package sources before installation."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from scripts.validate_release_policy import derive_package_version
except ModuleNotFoundError:  # Running directly from the scripts directory during an image build.
    from validate_release_policy import derive_package_version

PACKAGE_VERSION = re.compile(r'^(?P<prefix>version\s*=\s*")[^"]+(?P<suffix>"\s*)$', re.MULTILINE)


def embed_build_metadata(
    *,
    package_file: Path,
    package_root: Path,
    package_version: str,
    build_version: str,
    build_revision: str,
) -> None:
    """Make package metadata and runtime build fields identify one artifact."""
    expected_package_version = (
        "0.0.0+local" if build_version == "local-dev" else derive_package_version(build_version)
    )
    if package_version != expected_package_version:
        raise ValueError(
            f"package version {package_version} does not match build version {build_version}"
        )
    package_text = package_file.read_text(encoding="utf-8")
    package_text, replacements = PACKAGE_VERSION.subn(
        rf'\g<prefix>{package_version}\g<suffix>', package_text, count=1
    )
    if replacements != 1:
        raise ValueError(f"could not update package version in {package_file}")
    package_file.write_text(package_text, encoding="utf-8")
    (package_root / "__init__.py").write_text(
        f"__version__ = {json.dumps(package_version)}\n", encoding="utf-8"
    )
    (package_root / "build_info.py").write_text(
        f"PACKAGE_VERSION = {json.dumps(package_version)}\n"
        f"BUILD_VERSION = {json.dumps(build_version)}\n"
        f"BUILD_REVISION = {json.dumps(build_revision)}\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-file", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--package-root", type=Path, default=Path("src/lifeos"))
    parser.add_argument("--package-version", required=True)
    parser.add_argument("--build-version", required=True)
    parser.add_argument("--build-revision", required=True)
    args = parser.parse_args()
    embed_build_metadata(
        package_file=args.package_file,
        package_root=args.package_root,
        package_version=args.package_version,
        build_version=args.build_version,
        build_revision=args.build_revision,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
