# LifeOS operations

LifeOS is deployed through the Git-backed `bcl1713/homelab-stacks` repository. Do not deploy directly from the application repository.

## Live deployment

- Portainer stack: `app-lifeos` (endpoint 3)
- Git source: `https://github.com/bcl1713/homelab-stacks.git`
- Compose path: `stacks/apps/lifeos/compose.yaml`
- Current image: `ghcr.io/bcl1713/lifeos:v0.2.1`
- Current application revision: `a6d0b8931aa22bbd930285e0dc747fe2a7a83fa6`
- Access: private LAN/Tailscale through the external `proxy` network
- Hostname: `https://lifeos.hblucas.org`
- Application data: `/mnt/TANK/docker/lifeos/data` → `/data`
- Backups: `/mnt/TANK/backups/lifeos` → `/backups`
- No host port is published.

NPM forwards `lifeos.hblucas.org` to `lifeos:8000`. Pi-hole resolves the hostname to NPM at `10.10.50.4`; Pi-hole itself listens at `10.10.50.3`.

## Secrets

The human password and Jarvis agent token are stored in the Vaultwarden `LifeOS` item in the shared `Jarvis` collection. They are passed to Portainer as environment values and are never committed.

Configured values include:

- `LIFEOS_IMAGE` — immutable semantic-version tag or digest
- `LIFEOS_USERNAME`
- `LIFEOS_PASSWORD`
- `LIFEOS_AGENT_TOKEN`
- `LIFEOS_DATA_PATH`
- `LIFEOS_BACKUP_PATH`
- `LIFEOS_SCHEDULER_ENABLED`
- `LIFEOS_SCHEDULER_INTERVAL_SECONDS`
- `LIFEOS_TIMEZONE`

## Startup and persistence

1. The entrypoint prepares the bind-mounted `/data` directory.
2. The container runs `alembic upgrade head` before Uvicorn.
3. SQLite uses WAL and foreign-key enforcement.
4. Routine generation runs in the application container with idempotent occurrence keys.
5. The application runs as the unprivileged `lifeos` user after startup preparation.

## Backup and restore

Create an online backup from the running container as root so the backup mount remains writable regardless of host UID mapping:

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

A live backup was created and verified during deployment at `/backups/lifeos-live-v0.2.0.db`. The staging restore rehearsal also verified task and audit history.

The approved retention policy remains **30 daily / 12 monthly**. Automated retention scheduling still needs to be added at the infrastructure layer.

## Google Tasks migration rehearsal

The read-only source inventory currently contains 49 records:

- My Tasks: 16 — 2 open, 14 completed
- Family Triage: 33 — 3 open, 30 completed

The staging rehearsal selected all 49 records under the agreed rule: all open records plus completed records updated within the previous 12 months. It created 49 tasks and 49 migration audit records, and a second run created 0 duplicates.

The migration adapter is offline and deterministic. It does not write to Google Tasks. It preserves list, title, notes, due date, status, and a source marker containing the Google list/task IDs.

Production cutover is not yet approved. Until explicit cutover approval, Google Tasks remains read-only source data and LifeOS is not yet the sole active task authority.

## Verification targets

Verified:

- Container `app-lifeos-lifeos-1` is healthy.
- `https://lifeos.hblucas.org/healthz` returns HTTP 200 and version `0.2.1`.
- Browser login succeeds through the private hostname.
- Agent bearer authentication succeeds.
- Authenticated task creation, completion, and read-back succeed.
- `/data` and `/backups` are mounted.
- Backup creation and integrity verification succeed.
- Google Tasks staging counts reconcile exactly.

Remaining before cutover:

- Add scheduled 30-daily/12-monthly backup retention.
- Perform a final production backup immediately before import.
- Obtain explicit approval for the final Google Tasks delta import and write cutover.
- Disable Google Tasks writes only after final read-back verification.
- Verify the rollback path after the cutover decision.

## Portainer Git redeploy note

Portainer retained Git metadata but initially redeployed a cached compose file and stale image content. The deployment was corrected by explicitly pulling the GHCR image and applying the pushed compose content. The live service is healthy, but Portainer’s one-click Git redeploy path should be separately repaired or verified before relying on it for unattended releases.
