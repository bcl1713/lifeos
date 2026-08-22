# LifeOS operations

LifeOS is deployed through the Git-backed `bcl1713/homelab-stacks` repository. Do not deploy directly from the application repository.

## Live deployment

- Portainer stack: `app-lifeos` (stack `170`, endpoint `3`)
- Git source: `https://github.com/bcl1713/homelab-stacks.git`
- Compose path: `stacks/apps/lifeos/compose.yaml`
- Current production image: `ghcr.io/bcl1713/lifeos:v0.6.2` (`sha256:980b95928e0404c0e94e8bcc47088d391466a05c57614ef2adcb5f2970f2314d`)
- Pre-cutover rollback image: `ghcr.io/bcl1713/lifeos:v0.5.0`. Releases `v0.6.0` and `v0.6.1` were superseded before deployment by supplementary-group and symlink-safety findings; neither was accepted in production.
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

## Canonical source navigation

Projects and Areas display their canonical wiki path and an **Open canonical
note** action. With no additional configuration, the action opens LifeOS's
authenticated `/sources/wiki/...` rendered-source route. The route reads the
current canonical Markdown and keeps validated wikilinks and relative `.md`
links inside LifeOS; invalid or unsafe targets are rendered with diagnostics,
not anchors.

To make the canonical-note action open SilverBullet instead, set
`LIFEOS_SILVERBULLET_BASE_URL` to the reachable base URL for the same mounted
canonical wiki. LifeOS appends the URL-encoded root-relative canonical path
without `.md`. This is optional: LifeOS does not operate, authenticate, or
health-check SilverBullet, and rendered in-wiki navigation remains internal
even when the variable is set. Verify a Project and Area path (including a path
with spaces) after changing the setting. Full behavior and safety guidance:
`docs/rendered-source-navigation.md`.

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

### Task owner reconciliation

This section records the target operator contract for implementation PR [#27](https://github.com/bcl1713/lifeos/pull/27). It is not available on current `dev`; do not use it until that PR has merged and the running image includes it. Once available, task ownership will be part of the canonical-source contract. New tasks will be created only with `owner_type: project` or `area` plus an `owner_wiki_id` resolving to the same canonical type, or with `owner_type: inbox`, no owner ID, and the `Inbox` task list. The creation path will be deterministic: Project/Area tasks will live under the owning note's sibling `tasks/` directory; Inbox tasks will live under `00-Inbox/tasks/`.

After #27 is deployed, `sync_wiki_projection.py --check` will report `invalid_task_owners` when a task declares incomplete ownership, an invalid Inbox combination, a missing owner, or an owner whose canonical type does not match `owner_type`. A writable sync will refuse these invalid declared-owner records before projection mutation. Until then, this category is unavailable and operators must continue using the existing reconciliation output. After implementation, ownerless legacy source records will remain discoverable and will not by themselves make this new reconciliation category fail; they will require explicit owner assignment only when a controlled migration or relocation is separately authorized.

After #27 is deployed, before changing existing task ownership, take and verify the normal wiki and SQLite backups, run `--check`, and use the future controlled-relocation workflow once it is delivered. Do not hand-edit `owner_type`, `owner_wiki_id`, or `wiki_path` as a substitute: the implemented ordinary task updates will preserve the existing source path and reject owner reassignment with HTTP `409`. This delivery adds neither an automatic/live migration nor a scheduled/default-profile reconciliation job; reconciliation remains an explicit normal release, restart, recovery, or operator change-handling step.

Rebuild only after verified wiki and SQLite backups:

```bash
python scripts/sync_wiki_projection.py \
  --database sqlite:///./data/lifeos.db \
  --wiki-root /wiki
```

Sync never adopts an unidentified legacy row by title. Stable wiki ID and
canonical path—not title resemblance—control identity.

### Canonical-ID authority and duplicate recovery

This contract is implemented by [issue #11](https://github.com/bcl1713/lifeos/issues/11)
and its implementation PR [#14](https://github.com/bcl1713/lifeos/pull/14). It
extends the archived-relationship recovery rule below; use an image that includes
both behaviors before relying on this procedure.

`/wiki` is the source of record and SQLite is a rebuildable projection. For each
canonical ID, the authority rule is deliberately narrow:

- Exactly one non-`04-Archives/` candidate of one type is authoritative over one
  or more copies of that same ID and type in `04-Archives/`. The non-archive
  record supplies the projected data; the archive copies are retained as source
  history.
- If the only candidate is under `04-Archives/`, that archive-only record is
  authoritative. A typed archive-only record remains a valid relationship
  target; for example, an active Task may retain `project_wiki_id` for an
  archived Project.
- Two or more candidates at the same precedence (for example two non-archive
  copies, or two archive-only copies), or candidates with one ID but different
  types, are **ambiguous**. They are strict preflight failures. Sync stops before
  any projection mutation; it must not choose a record by title, path ordering,
  or an existing SQLite row.

Run the non-mutating gate first. Its JSON report distinguishes allowed copies
from ambiguity:

```bash
python scripts/sync_wiki_projection.py \
  --database sqlite:///./data/lifeos.db \
  --wiki-root /wiki \
  --check
```

`shadowed_archive_ids` lists the permitted active-plus-archive copies and does
not by itself make the report unaligned. `authority_conflicts` lists ambiguous
canonical IDs and keeps the report blocking (`aligned: false` and exit status
`2`). Treat every item in `authority_conflicts` as a stop condition, even if the
SQLite projection appears healthy. The check also continues to report missing or
wrong-type relationship targets.

The command neither rewrites canonical source nor modifies SQLite automatically
when resolving authority. Do not use title matching, manual SQLite edits, or a
projection rebuild to "fix" an ambiguous ID. Preserve backups, investigate the
canonical Markdown records, and make any deliberate source correction through
the approved operator process; then rerun `--check` until it is aligned before a
writable rebuild.

### Recovering a projection-sync relationship failure

A target that is genuinely missing, or whose canonical type does not match the
relationship, is a reconciliation failure. The `--check` report identifies the
source `id`, relationship `field`, `target_id`, and `expected_type`; writable
sync formats the same diagnostic as `source-id.field -> target-id
(expected-type)`. Sync does **not** repair, delete, rewrite, or detach canonical
source relationships automatically.

Image rollback can change application code, but it does not repair malformed
canonical-source relationship state or ambiguity.

1. Make and verify fresh SQLite and wiki backups before any writable sync. Set
   `CONTAINER` to the running LifeOS container and keep both backup paths with
   the incident record:

   ```bash
   CONTAINER=app-lifeos-lifeos-1
   BACKUP_TS=$(date -u +%Y%m%dT%H%M%SZ)
   SQLITE_BACKUP=/backups/projection-sync-${BACKUP_TS}.db
   WIKI_BACKUP=/backups/projection-sync-${BACKUP_TS}-wiki.tar.gz

   docker exec -u 0 "$CONTAINER" \
     python /app/scripts/backup_lifeos.py \
     --database /data/lifeos.db \
     --output "$SQLITE_BACKUP"
   docker exec "$CONTAINER" \
     python /app/scripts/verify_backup.py "$SQLITE_BACKUP"

   docker exec -u 0 "$CONTAINER" \
     python -c 'import sys, tarfile; source, destination = sys.argv[1:]; archive = tarfile.open(destination, "w:gz"); archive.add(source, arcname="wiki", recursive=True); archive.close()' \
     /wiki "$WIKI_BACKUP"
   docker exec "$CONTAINER" \
     python -c 'import sys, tarfile; archive = tarfile.open(sys.argv[1], "r:gz"); names = archive.getnames(); archive.close(); assert any(name == "wiki" or name.startswith("wiki/") for name in names), "wiki root missing from archive"; print(f"verified={sys.argv[1]} members={len(names)}")' \
     "$WIKI_BACKUP"
   ```

2. Run the non-mutating reconciliation gate and inspect every reported canonical
   source record and relationship. A nonzero exit means the projection is not
   aligned; do not proceed by changing SQLite or detaching the relationship:

   ```bash
   docker exec "$CONTAINER" \
     python /app/scripts/sync_wiki_projection.py \
     --database sqlite:////data/lifeos.db \
     --wiki-root /wiki \
     --check
   ```

3. If the target is missing or wrong-typed, restore it from the verified wiki
   backup or otherwise deliberately correct the canonical source through the
   approved operator process. Do not use projection sync as a source-repair
   tool. If the target is a typed record under `04-Archives`, leave the valid
   relationship intact and investigate only other reported discrepancies.

4. After the canonical source is deliberately corrected and the backups remain
   available, rebuild the writable SQLite projection, repeat the non-mutating
   check, then validate the service health endpoint:

   ```bash
   docker exec "$CONTAINER" \
     python /app/scripts/sync_wiki_projection.py \
     --database sqlite:////data/lifeos.db \
     --wiki-root /wiki

   docker exec "$CONTAINER" \
     python /app/scripts/sync_wiki_projection.py \
     --database sqlite:////data/lifeos.db \
     --wiki-root /wiki \
     --check

   curl --fail --silent --show-error https://lifeos.hblucas.org/healthz
   ```

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

**Production-copy 2026-08-12 rehearsal:** a hash-verified online copy of the live `v0.5.0` SQLite database and a hash-verified wiki archive were used without modifying production. Dry-run identified 77 application-only rows (2 Goals, 3 Projects, 4 Routines, and 68 Tasks). Apply created 77 canonical records, an idempotent rerun created zero, and an empty Alembic-head database rebuilt 99/99 records with zero reconciliation discrepancies and zero semantic differences across the migrated records. These counts describe the rehearsal copy only.

**Production acceptance 2026-08-12:** fresh pre-cutover backups were verified before stopping `v0.5.0`. Live dry-run identified 78 rows (2 Goals, 3 Projects, 4 Routines, and 69 Tasks); apply created 78 canonical records and the rerun planned zero changes. A fresh Alembic-head database rebuilt 100/100 source/projection records before acceptance writes. Source-first authenticated writes passed for all five canonical domains. A separate wiki UID/GID `3000` edit synchronized back through the authenticated API. Final reconciliation remained aligned at 105/105 after restart. The live image is `v0.6.2` at `sha256:980b95928e0404c0e94e8bcc47088d391466a05c57614ef2adcb5f2970f2314d`.

Post-deploy recovery evidence: `/backups/post-deploy-v0.6.2-20260813T001536Z.db` verified with 70 Tasks and 9 audit records; restore to a fresh temporary database produced identical counts and checksum. `/backups/post-deploy-v0.6.2-wiki-20260813T001536Z.tar.gz` passed archive verification. Retained artifacts are mode `0600`.

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

### Dev test artifacts

A successful push or merge to `dev` runs verification, the test suite, and the package build before it publishes a test artifact. The artifact has two immutable GHCR references:

- Candidate: `ghcr.io/bcl1713/lifeos:v<next-patch>-dev.<GitHub-run-number>`
- Commit: `ghcr.io/bcl1713/lifeos:sha-<commit>`

`<next-patch>` is derived as one greater than `[project].version` in `pyproject.toml`. The candidate and commit tags must resolve to the same digest. Failed checks and pull-request pushes publish nothing. There is deliberately no mutable `dev` tag, and this path neither creates `latest` or a stable tag nor deploys or promotes to production.

Before testing a dev candidate on a server, record the candidate/version or SHA reference and resolve its digest. Test only the recorded explicit tag or a digest-pinned reference, not a branch-like tag:

```bash
IMAGE=ghcr.io/bcl1713/lifeos:v<next-patch>-dev.<GitHub-run-number>
docker buildx imagetools inspect "$IMAGE" --format '{{.Manifest.Digest}}'
docker pull "$IMAGE"
docker image inspect "$IMAGE" --format '{{index .RepoDigests 0}}'
```

Also resolve `ghcr.io/bcl1713/lifeos:sha-<commit>` and confirm it reports the same manifest digest before any test result is used as promotion evidence. Preserve the exact tag and digest with the test record.

### Stable release, deployment, and rollback

RC publication remains a manual dispatch from `dev` using an explicit `vMAJOR.MINOR.PATCH-rc.N` input. Stable `vMAJOR.MINOR.PATCH` releases remain `main`-only after Brian approves the `dev` → `main` release gate.

Deployment changes belong only in `bcl1713/homelab-stacks`. Before stateful changes, verify a backup, record the current stack/image and digest, and preserve the bind mounts. To roll back, change the stack there to a previously tested explicit version or digest, then follow that repository's deployment procedure; roll back the image/stack definition first and do not delete `/mnt/TANK/docker/lifeos/data` during routine rollback.

## Health build identity and artifact verification

`GET /healthz` is a public liveness endpoint. A successful response has HTTP
`200` and these fields:

| Field | Meaning | Verification use |
| --- | --- | --- |
| `status` | Liveness result (`ok` when the service responds normally). | Confirms the endpoint is live; it is not an artifact identifier. |
| `service` | Service name (`lifeos`). | Identifies the responding service; it is not an artifact identifier. |
| `package_version` | Static Python package metadata from the installed LifeOS package. The current package metadata is `0.6.2`. | Confirms the application package metadata, not the deployed image release. |
| `build_version` | Immutable original build/release-channel version embedded when the image was built. | Compare with the inspected artifact's OCI version label. |
| `build_revision` | Immutable source Git commit embedded when the image was built. | Compare with the inspected artifact's OCI revision label. |

`build_version` is not a mutable deployment tag. For example, a later release
alias may be attached to an existing image digest without rebuilding it; that
artifact continues to report the original `build_version` and
`build_revision`. Do not use `package_version`, `build_version`, or
`build_revision` as evidence of which image reference the deployment was
configured to use. Verify that reference separately.

### Operator procedure

Perform these steps against the intended deployment or a local copy of its
artifact. The commands use placeholders and do not require Portainer access or
application credentials.

1. Record the configured image reference independently. For a Compose file,
   render the selected configuration; for a running container, record its
   configured image value:

   ```bash
   docker compose -f <compose-file> config | grep 'image:'
   docker inspect <container> --format '{{.Config.Image}}'
   ```

   Prefer a digest-pinned reference. If a tag is configured, resolve and record
   the corresponding digest before accepting the deployment; a tag alone can
   move to a different artifact.

2. Inspect the exact image artifact selected in step 1. Substitute either the
   recorded digest or a locally available image reference for `<image-ref>`:

   ```bash
   docker image inspect <image-ref> --format '{{range .RepoDigests}}{{println .}}{{end}}'
   docker image inspect <image-ref> --format '{{index .Config.Labels "org.opencontainers.image.version"}}'
   docker image inspect <image-ref> --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
   ```

   Save the resolved `RepoDigest` together with the two OCI label values. The
   labels `org.opencontainers.image.version` and
   `org.opencontainers.image.revision` identify the immutable build metadata
   embedded in that artifact.

3. Retrieve health data from the intended endpoint and compare only values from
   the same artifact:

   ```bash
   curl --fail --silent --show-error <lifeos-base-url>/healthz | python3 -m json.tool
   ```

   Confirm `status` is `ok` and `service` is `lifeos`. Confirm
   `build_version` exactly matches
   `org.opencontainers.image.version`, and `build_revision` exactly matches
   `org.opencontainers.image.revision` from step 2. Record the configured
   image tag or digest separately from those comparisons. A mismatch means the
   endpoint and inspected artifact are not proven to be the same build and
   requires investigation before release acceptance or rollback completion.

For locally built development images, `build_version` may be `local-dev` and
`build_revision` may be `unknown`; these defaults are not release identity and
must not be accepted as production artifact evidence.
