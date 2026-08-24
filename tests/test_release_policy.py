from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_release_policy import (
    derive_dev_version,
    derive_package_version,
    package_version,
    validate_release,
    validate_repository,
)


@pytest.mark.parametrize(
    ("version", "package_version"),
    [
        ("v0.6.10-rc.1", "0.6.9"),
        ("v12.34.56-rc.99", "12.34.55"),
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
    [("v0.6.10", "0.6.9"), ("v12.34.56", "12.34.55")],
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


@pytest.mark.parametrize(
    ("version", "mode"),
    [("v0.6.3-rc.1", "rc"), ("v0.6.3", "stable")],
)
def test_release_accepts_the_next_artifact_identity_from_current_package_metadata(version: str, mode: str) -> None:
    current_package_version = package_version(Path("pyproject.toml"))

    assert current_package_version == "0.6.2"
    assert validate_release(version, current_package_version, mode) == []


def test_release_rejects_semver_core_numbers_with_leading_zeroes() -> None:
    assert validate_release("v01.7.0-rc.1", "01.7.0", "rc")
    assert validate_release("v01.7.0", "01.7.0", "stable")


@pytest.mark.parametrize(
    ("package_version", "run_number", "expected"),
    [
        ("0.6.2", "1234", "v0.6.3-dev.1234"),
        ("12.34.56", "99", "v12.34.57-dev.99"),
    ],
)
def test_dev_release_derives_a_unique_next_patch_semver_prerelease(
    package_version: str, run_number: str, expected: str
) -> None:
    assert derive_dev_version(package_version, run_number) == expected


@pytest.mark.parametrize(
    ("build_version", "expected"),
    [
        ("v0.6.3-dev.51", "0.6.3.dev51"),
        ("v0.6.3-rc.1", "0.6.3rc1"),
        ("v0.6.3", "0.6.3"),
    ],
)
def test_artifact_package_version_uses_pep440_identity(build_version: str, expected: str) -> None:
    assert derive_package_version(build_version) == expected


@pytest.mark.parametrize("build_version", ["0.6.3", "v0.6.3-dev.0", "v0.6.3-rc.0", "v0.06.3"])
def test_artifact_package_version_rejects_non_release_build_versions(build_version: str) -> None:
    with pytest.raises(ValueError, match="artifact build version"):
        derive_package_version(build_version)


@pytest.mark.parametrize("package_version", ["0.6", "01.6.2", "0.6.02", "v0.6.2"])
def test_dev_release_rejects_an_invalid_package_version(package_version: str) -> None:
    with pytest.raises(ValueError, match="package version"):
        derive_dev_version(package_version, "1234")


@pytest.mark.parametrize("run_number", ["0", "01", "run-1234"])
def test_dev_release_rejects_an_invalid_run_number(run_number: str) -> None:
    with pytest.raises(ValueError, match="run number"):
        derive_dev_version("0.6.2", run_number)


def test_repository_release_workflows_enforce_channel_boundaries() -> None:
    errors = validate_repository(Path("."))

    assert errors == []


def test_release_workflow_builds_a_distinct_artifact_for_each_unpublished_release_version() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "steps.immutable_tags.outputs.version_unpublished == 'true'" in workflow
    assert "LIFEOS_BUILD_VERSION=${{ needs.verify.outputs.version }}" in workflow
    assert "package_version: ${{ steps.release.outputs.package_version }}" in workflow
    assert "LIFEOS_PACKAGE_VERSION=${{ needs.verify.outputs.package_version }}" in workflow
    assert 'docker buildx imagetools create --tag "ghcr.io/bcl1713/lifeos:$VERSION"' not in workflow
    assert "version_revision" in workflow
    assert "version_label" in workflow
    assert "refusing to use existing image tag" in workflow
