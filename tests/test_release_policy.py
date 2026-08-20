from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_release_policy import validate_release, validate_repository


@pytest.mark.parametrize(
    ("version", "package_version"),
    [
        ("v0.7.0-rc.1", "0.7.0"),
        ("v12.34.56-rc.99", "12.34.56"),
    ],
)
def test_rc_release_accepts_matching_semver_prerelease(version: str, package_version: str) -> None:
    assert validate_release(version, package_version, "rc") == []


@pytest.mark.parametrize(
    "version",
    ["v0.7.0", "v0.7.0-rc.0", "v0.7.0-rc1", "v0.7-rc.1", "v01.7.0-rc.1", "release-0.7.0-rc.1"],
)
def test_rc_release_rejects_final_and_malformed_versions(version: str) -> None:
    assert validate_release(version, "0.7.0", "rc")


@pytest.mark.parametrize(
    ("version", "package_version"),
    [("v0.7.0", "0.7.0"), ("v12.34.56", "12.34.56")],
)
def test_stable_release_accepts_matching_final_semver(version: str, package_version: str) -> None:
    assert validate_release(version, package_version, "stable") == []


@pytest.mark.parametrize(
    "version",
    ["v0.7.0-rc.1", "v0.7", "v0.7.0-rc1", "v01.7.0", "release-0.7.0"],
)
def test_stable_release_rejects_prerelease_and_malformed_versions(version: str) -> None:
    assert validate_release(version, "0.7.0", "stable")


def test_release_rejects_a_package_version_mismatch() -> None:
    assert validate_release("v0.7.0-rc.1", "0.7.1", "rc")
    assert validate_release("v0.7.0", "0.7.1", "stable")


def test_release_rejects_semver_core_numbers_with_leading_zeroes() -> None:
    assert validate_release("v01.7.0-rc.1", "01.7.0", "rc")
    assert validate_release("v01.7.0", "01.7.0", "stable")


def test_repository_release_workflows_enforce_channel_boundaries() -> None:
    errors = validate_repository(Path("."))

    assert errors == []
