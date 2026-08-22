import os
import stat
import subprocess
import sys
from pathlib import Path


def test_entrypoint_preserves_only_explicit_supplementary_gids() -> None:
    script = Path("docker-entrypoint.sh").read_text(encoding="utf-8")

    assert "LIFEOS_SUPPLEMENTARY_GIDS" in script
    assert "setpriv" in script
    assert "--groups" in script
    assert "runuser" not in script
    assert 'chown -R lifeos:lifeos "$canonical_root"' not in script
    assert 'chown lifeos:"$canonical_gid" "$canonical_root"' not in script
    assert "prepare_wiki_permissions.py" in script
    assert 'chgrp "$canonical_gid" "$canonical_root"' not in script
    assert 'chmod 2775 "$canonical_root"' not in script
    assert "umask 0002" in script


def test_container_build_embeds_release_identity_and_workflow_passes_it() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "ARG LIFEOS_BUILD_VERSION=local-dev" in dockerfile
    assert "ARG LIFEOS_BUILD_REVISION=unknown" in dockerfile
    assert "org.opencontainers.image.version=$LIFEOS_BUILD_VERSION" in dockerfile
    assert "org.opencontainers.image.revision=$LIFEOS_BUILD_REVISION" in dockerfile
    assert "src/lifeos/build_info.py" in dockerfile
    assert "LIFEOS_BUILD_VERSION=${{ needs.verify.outputs.version }}" in workflow
    assert "LIFEOS_BUILD_REVISION=${{ github.sha }}" in workflow


def test_entrypoint_validates_supplementary_gids_before_privilege_drop() -> None:
    script = Path("docker-entrypoint.sh").read_text(encoding="utf-8")

    assert "invalid LIFEOS_SUPPLEMENTARY_GIDS" in script
    assert "*[!0-9,]*" in script
    assert "*,0*" in script
    assert '"${#supplementary_gid}" -gt 10' in script
    assert '"$supplementary_gid" -gt 4294967294' in script


def test_phase8_validator_accepts_the_setpriv_identity_contract() -> None:
    validator = Path("scripts/validate_phase8_deployment.py").read_text(encoding="utf-8")

    assert '"setpriv --reuid=lifeos --regid=lifeos" in entrypoint' in validator
    assert '"--clear-groups" in entrypoint' in validator
    assert "runuser -u lifeos" not in validator
    assert "source distribution must include operational Python scripts" in validator


def test_permission_helper_uses_directory_descriptors_without_following_symlinks() -> None:
    helper = Path("scripts/prepare_wiki_permissions.py").read_text(encoding="utf-8")

    assert "os.O_NOFOLLOW" in helper
    assert "dir_fd=current_fd" in helper
    assert "os.fchown(current_fd" in helper
    assert "os.fchmod(current_fd" in helper
    assert "os.fchown(child_fd, parent_stat.st_uid, parent_stat.st_gid)" in helper


def test_permission_helper_rejects_symlink_without_mutating_target(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    parent = wiki / "01-Projects" / "LifeOS"
    parent.mkdir(parents=True)
    target = tmp_path / "target"
    target.mkdir(mode=0o755)
    (parent / "lifeos").symlink_to(target, target_is_directory=True)
    before = (target.stat().st_uid, target.stat().st_gid, stat.S_IMODE(target.stat().st_mode))

    result = subprocess.run(
        [sys.executable, "scripts/prepare_wiki_permissions.py", "--wiki-root", str(wiki), "--supplementary-gid", "3000"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 64
    assert "refusing unsafe canonical wiki path" in result.stderr
    assert (target.stat().st_uid, target.stat().st_gid, stat.S_IMODE(target.stat().st_mode)) == before


def test_permission_helper_rejects_intermediate_symlink(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    target = tmp_path / "projects-target"
    target.mkdir(mode=0o755)
    (wiki / "01-Projects").symlink_to(target, target_is_directory=True)
    before = os.stat(target)

    result = subprocess.run(
        [sys.executable, "scripts/prepare_wiki_permissions.py", "--wiki-root", str(wiki), "--supplementary-gid", "3000"],
        capture_output=True,
        text=True,
        check=False,
    )

    after = os.stat(target)
    assert result.returncode == 64
    assert (after.st_uid, after.st_gid, stat.S_IMODE(after.st_mode)) == (
        before.st_uid,
        before.st_gid,
        stat.S_IMODE(before.st_mode),
    )


def test_permission_helper_new_subtree_inherits_parent_owner(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    parent_owner = (wiki.stat().st_uid, wiki.stat().st_gid)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/prepare_wiki_permissions.py",
            "--wiki-root",
            str(wiki),
            "--supplementary-gid",
            str(parent_owner[1]),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    canonical = wiki / "01-Projects" / "LifeOS" / "lifeos"
    assert result.returncode == 0
    assert (canonical.stat().st_uid, canonical.stat().st_gid) == parent_owner
    assert stat.S_IMODE(canonical.stat().st_mode) == 0o2775