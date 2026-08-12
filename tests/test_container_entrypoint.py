from pathlib import Path


def test_entrypoint_preserves_only_explicit_supplementary_gids() -> None:
    script = Path("docker-entrypoint.sh").read_text(encoding="utf-8")

    assert "LIFEOS_SUPPLEMENTARY_GIDS" in script
    assert "setpriv" in script
    assert "--groups" in script
    assert "runuser" not in script
    assert 'chown -R lifeos:lifeos "$canonical_root"' not in script
    assert 'chown lifeos:"$canonical_gid" "$canonical_root"' not in script
    assert 'chgrp "$canonical_gid" "$canonical_root"' in script
    assert 'chmod 2775 "$canonical_root"' in script
    assert "umask 0002" in script


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