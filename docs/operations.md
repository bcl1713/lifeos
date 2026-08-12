# LifeOS operations

LifeOS is deployed through the Git-backed `bcl1713/homelab-stacks` repository. Do not deploy directly from the application repository.

## Live deployment

- Portainer stack: `app-lifeos` (stack `170`, endpoint `3`)
- Git source: `https://github.com/bcl1713/homelab-stacks.git`
- Compose path: `stacks/apps/lifeos/compose.yaml`
- Pre-cutover production image: `ghcr.io/bcl1713/lifeos:v0.5.0`
- Target wiki-first release: `v0.6.1`; `v0.6.0` is superseded before deployment because its privilege drop discarded the production wiki supplementary group. Do not record `v0.6.1` as current until live version, image, reconciliation, restart, and authenticated read-back pass.
- Access: private LAN/Tailscale through the external `proxy` network
- Hostname: `https://lifeos.hblucas.org`
- Application data: `/mnt/TANK/docker/lifeos/data` → `/data`
- Backups: `/mnt/TANK/backups/lifeos` → `/backups`
- No host port is published.

Nginx Proxy Manager forwards `lifeos.hblucas.org` to `lifeos:8000`. Pi-hole resolves the hostname to NPM at `10.10.50.4`; Pi-hole itself listens at `10.10.50.3`.

## Secrets

The human password and Jarvis agent token are stored in the Vaultwarden `LifeOS` item in the shared `Jarvis` collection. They are passed to Portainer as environment values and are never committed or printed.

## Startup, identity, and persistence

1. The entrypoint prepares the bind-mounted `/data` directory as root.
2. Alembic upgrades run before Uvicorn.
3. The application process runs as unprivileged UID/GID `100:101` (`lifeos`).
4. `/wiki` is the canonical durable authority for Tasks, Projects, Areas, Goals, and Routines; SQLite uses WAL and foreign-key enforcement only as a rebuildable projection, query index, and audit cache.
5. Domain mutations write Markdown source-first. Updates require `expected_hash`; stale source produces HTTP `409` and no projection commit.
6. Routine generation runs in the application container with idempotent canonical occurrence keys.
7. Startup/release acceptance requires projection reconciliation, not merely a healthy SQLite file or HTTP health response.

## Backup and restore

Create an online backup from the running container:

```bash
docker exec -u 0 app-lifeos-lifeos-1 \
  python /app/scripts/backup_lifeos.py \
  --database /data/lifeos.db \
  --output /backups/lifeos-$(date -u +%Y%m%dT%H%M%SZ).db
```

Verify a backup:

```bash
docker exec app-lifeos-lifeos-1 \
  python /app/scripts/verify_backup.py /backups/<backup-file>.db
```

Export portable JSON:

```bash
docker exec app-lifeos-lifeos-1 \
  python /app/scripts/export_lifeos.py \
  /data/lifeos.db /backups/lifeos-export-$(date -u +%Y%m%dT%H%M%SZ).json
```

Retention policy: **30 daily / 12 monthly**. The retention tool supports a dry run and explicit `--apply`; unattended scheduling remains an infrastructure-level operational choice and is not claimed here as implemented.

## Migration and authority

The read-only Google Tasks inventory contained 2 lists and 49 records:

- My Tasks: 16 — 2 open, 14 completed
- Family Triage: 33 — 3 open, 30 completed

All 49 were imported with source markers during the earlier application-authority phase. That authority statement is superseded by the wiki-first model: canonical Task state now belongs in wiki Markdown, while LifeOS provides the authenticated workflow and rebuildable execution projection. Google Tasks remains read-only historical source data; scheduled workflows contain no Google Tasks writer commands.

Rollback is documented: restore the read-only Google Tasks export and re-enable the retired path only if cutover verification fails. No routine writes to both systems.

## Projection reconciliation

Validate the authoritative Project and Area index links separately for each dataset:

```bash
python scripts/validate_wiki_links.py /home/brian/wiki
python scripts/validate_wiki_links.py /wiki
```

The validator resolves extensionless and mixed-case final `Index.md` components, rejects traversal, and reports missing or ambiguous targets without mutating the wiki.

Run a non-mutating check before and after rebuild, release, restart, or recovery:

```bash
python scripts/sync_wiki_projection.py \
  --database sqlite:///./data/lifeos.db \
  --wiki-root /wiki \
  --check
```

The command exits `0` only when canonical source and projection align. Missing, orphaned, duplicate, stale-hash, type/path-conflict, missing-identity, or invalid-link records must be resolved or explicitly waived before deployment acceptance.

Rebuild only after verified wiki and SQLite backups:

```bash
python scripts/sync_wiki_projection.py \
  --database sqlite:///./data/lifeos.db \
  --wiki-root /wiki
```

Sync refuses duplicate canonical IDs before projection mutation and never adopts an unidentified legacy row by title. Stable wiki ID and canonical path—not title resemblance—control identity.

Before the first writable wiki cutover, canonicalize any application-only domain rows using the dry-run-first migration command:

```bash
python scripts/canonicalize_legacy_projection.py \
  --database sqlite:////data/lifeos.db \
  --wiki-root /wiki

# Only after verified SQLite and wiki backups plus a successful rehearsal:
python scripts/canonicalize_legacy_projection.py \
  --database sqlite:////data/lifeos.db \
  --wiki-root /wiki \
  --apply
```

The migration assigns deterministic non-title IDs, records projection-row provenance, writes canonical Markdown before updating identities, preserves relationships and related state, and is safe to rerun after a partial interruption.

**Local 2026-08-12 rehearsal:** `/home/brian/wiki` produced 22 canonical records (12 Projects and 10 Areas); a fresh Alembic-head database rebuilt 22 projection records with zero unexplained discrepancies and SQLite integrity `ok`. This is local evidence only. Production source counts and reconciliation must be measured separately during rollout.

**Production-copy 2026-08-12 rehearsal:** a hash-verified online copy of the live `v0.5.0` SQLite database and a hash-verified wiki archive were used without modifying production. Dry-run identified 77 application-only rows (2 Goals, 3 Projects, 4 Routines, and 68 Tasks). Apply created 77 canonical records, an idempotent rerun created zero, and an empty Alembic-head database rebuilt 99/99 records with zero reconciliation discrepancies and zero semantic differences across the migrated records. This proves the migration path only; fresh live backups, production apply, writable deployment, and authenticated acceptance remain separate gates.

## Historical production verification snapshot

The following evidence describes release `v0.3.8`; it is retained for older rollback history and must not be read as proof of the current `v0.5.0` baseline or wiki-first release:

- `https://lifeos.hblucas.org/healthz`: HTTP `200`, version `0.3.8`
- Browser `/auth/me`, `/`, `/tasks`: HTTP `200`
- Agent task read/create/complete/read-back/archive: `200/201/200/200/200`
- Pre-recreation backup: `/backups/pre-phase8-git-repair.db`, `tasks=64`, `audit_records=149`
- Post-change backup: `/backups/post-phase8.db`, `tasks=65`, `audit_records=152`
- Full test suite: 33 passed
- Phase 5–10 validators: valid
- Wiki provenance: 620 notes scanned, 0 schema errors, bounded legacy warnings

## Release and rollback

Use an immutable semantic-version image tag or digest. Before stateful changes, verify a backup, record the current stack/image, and preserve the bind mounts. Roll back the image/stack definition first; do not delete `/mnt/TANK/docker/lifeos/data` during routine rollback.
