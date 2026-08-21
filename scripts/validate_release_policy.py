#!/usr/bin/env python3
"""Validate LifeOS release versions and release-workflow safety boundaries."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

SEMVER_CORE = r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
RC_VERSION = re.compile(rf"^v(?P<version>{SEMVER_CORE})-rc\.(?:[1-9]\d*)$")
STABLE_VERSION = re.compile(rf"^v(?P<version>{SEMVER_CORE})$")
PACKAGE_SEMVER = re.compile(rf"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$")
RUN_NUMBER = re.compile(r"^[1-9]\d*$")
PACKAGE_VERSION = re.compile(rf'^version\s*=\s*"(?P<version>{SEMVER_CORE})"\s*$', re.MULTILINE)


def derive_dev_version(package_version: str, run_number: str) -> str:
    """Derive a unique, strict SemVer dev prerelease from package metadata."""
    package_match = PACKAGE_SEMVER.fullmatch(package_version)
    if package_match is None:
        raise ValueError(f"invalid package version: {package_version}")
    if RUN_NUMBER.fullmatch(run_number) is None:
        raise ValueError(f"invalid GitHub run number: {run_number}")
    return (
        f"v{package_match.group('major')}.{package_match.group('minor')}"
        f".{int(package_match.group('patch')) + 1}-dev.{run_number}"
    )


def validate_release(version: str, package_version: str, mode: str) -> list[str]:
    """Return policy violations for a requested release version."""
    patterns = {"rc": RC_VERSION, "stable": STABLE_VERSION}
    if mode not in patterns:
        return [f"unsupported release mode: {mode}"]

    match = patterns[mode].fullmatch(version)
    if not match:
        expected = "vMAJOR.MINOR.PATCH-rc.N" if mode == "rc" else "vMAJOR.MINOR.PATCH"
        return [f"{mode} release version must match {expected}: {version}"]
    if match.group("version") != package_version:
        return [f"release version {version} does not match package version {package_version}"]
    return []


def package_version(package_file: Path) -> str | None:
    match = PACKAGE_VERSION.search(package_file.read_text(encoding="utf-8"))
    return match.group("version") if match else None


def validate_repository(repository: Path) -> list[str]:
    """Return release-policy workflow violations in a repository checkout."""
    errors: list[str] = []
    ci_file = repository / ".github/workflows/ci.yml"
    release_file = repository / ".github/workflows/release.yml"
    ci = ci_file.read_text(encoding="utf-8") if ci_file.is_file() else ""
    release = release_file.read_text(encoding="utf-8") if release_file.is_file() else ""

    for phrase in ("branches: [main, dev]", "pull_request:"):
        if phrase not in ci:
            errors.append(f"CI workflow missing branch coverage: {phrase}")

    required_release_fragments = (
        "branches: [dev]",
        "group: release-${{ github.ref }}",
        "workflow_dispatch:",
        "release_candidate_version:",
        '"${{ github.event_name }}" = "push"',
        '"${{ github.ref }}" = "refs/heads/dev"',
        "--mode dev --run-number \"$GITHUB_RUN_NUMBER\"",
        '"${{ github.ref }}" != "refs/heads/dev"',
        "--mode rc",
        "--mode stable",
        "git fetch origin main --no-tags",
        'git rev-parse "origin/main^{commit}"',
        "uv run pytest",
        "uv build",
        "type=raw,value=${{ needs.verify.outputs.version }}",
        "type=raw,value=sha-${{ github.sha }}",
        "id: immutable_tags",
        "echo \"sha_unpublished=false\" >> \"$GITHUB_OUTPUT\"",
        "echo \"version_unpublished=false\" >> \"$GITHUB_OUTPUT\"",
        "version_digest",
        "sha_digest",
        "enable=${{ steps.immutable_tags.outputs.sha_unpublished }}",
        "steps.immutable_tags.outputs.sha_unpublished == 'true'",
        "docker buildx imagetools create --tag \"ghcr.io/bcl1713/lifeos:$VERSION\"",
        "--generate-notes",
        "--prerelease",
        "gh release view \"$VERSION\"",
        "--json targetCommitish --jq .targetCommitish",
        'if [ "$CHANNEL" = "stable" ]; then',
    )
    for phrase in required_release_fragments:
        if phrase not in release:
            errors.append(f"release workflow missing safety control: {phrase}")
    forbidden_release_fragments = ("type=raw,value=latest", "type=ref,event=branch", "git tag ", "git push")
    if any(fragment in release for fragment in forbidden_release_fragments):
        errors.append("release workflow must not publish latest, branch, or CI-pushed Git tags")
    if "deploy" in release.lower():
        errors.append("release workflow must not deploy")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dev", "rc", "stable"))
    parser.add_argument("--version")
    parser.add_argument("--run-number")
    parser.add_argument("--package-file", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--repository", type=Path)
    args = parser.parse_args()

    errors: list[str] = []
    if args.repository:
        errors.extend(validate_repository(args.repository))
    if args.mode == "dev":
        if args.version or not args.run_number:
            parser.error("--mode dev requires --run-number and does not accept --version")
        resolved_package_version = package_version(args.package_file)
        if resolved_package_version is None:
            errors.append(f"could not read package version from {args.package_file}")
        else:
            try:
                print(derive_dev_version(resolved_package_version, args.run_number))
            except ValueError as error:
                errors.append(str(error))
    elif args.mode and args.version:
        resolved_package_version = package_version(args.package_file)
        if resolved_package_version is None:
            errors.append(f"could not read package version from {args.package_file}")
        else:
            errors.extend(validate_release(args.version, resolved_package_version, args.mode))
    elif args.mode or args.version or args.run_number:
        parser.error("--mode and --version must be used together")

    for error in errors:
        print(f"error: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
