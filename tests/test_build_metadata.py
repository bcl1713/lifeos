from pathlib import Path

import pytest

from scripts.embed_build_metadata import embed_build_metadata


@pytest.mark.parametrize(
    ("package_version", "build_version"),
    [
        ("0.6.3.dev51", "v0.6.3-dev.51"),
        ("0.6.3rc1", "v0.6.3-rc.1"),
        ("0.6.3", "v0.6.3"),
    ],
)
def test_embed_build_metadata_aligns_package_and_runtime_identity(
    tmp_path: Path, package_version: str, build_version: str
) -> None:
    package_file = tmp_path / "pyproject.toml"
    package_file.write_text('[project]\nname = "lifeos"\nversion = "0.6.2"\n', encoding="utf-8")
    package_root = tmp_path / "src" / "lifeos"
    package_root.mkdir(parents=True)

    embed_build_metadata(
        package_file=package_file,
        package_root=package_root,
        package_version=package_version,
        build_version=build_version,
        build_revision="a" * 40,
    )

    assert f'version = "{package_version}"' in package_file.read_text(encoding="utf-8")
    assert (package_root / "__init__.py").read_text(encoding="utf-8") == f'__version__ = "{package_version}"\n'
    assert (package_root / "build_info.py").read_text(encoding="utf-8") == (
        f'PACKAGE_VERSION = "{package_version}"\n'
        f'BUILD_VERSION = "{build_version}"\n'
        f'BUILD_REVISION = "{"a" * 40}"\n'
    )


def test_embed_build_metadata_rejects_mismatched_release_identity(tmp_path: Path) -> None:
    package_file = tmp_path / "pyproject.toml"
    package_file.write_text('[project]\nname = "lifeos"\nversion = "0.6.2"\n', encoding="utf-8")
    package_root = tmp_path / "src" / "lifeos"
    package_root.mkdir(parents=True)

    with pytest.raises(ValueError, match="does not match"):
        embed_build_metadata(
            package_file=package_file,
            package_root=package_root,
            package_version="0.6.2",
            build_version="v0.6.3-dev.51",
            build_revision="a" * 40,
        )
