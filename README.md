# LifeOS

Private life operating system for tasks, routines, goals, projects, reviews, and selected life data.

## Status

Initial application scaffold plus authenticated domain API and automatic routine-task generation.

- `/healthz` is public.
- `/auth/login`, `/auth/logout`, `/auth/me`, and agent bearer authentication are available.
- Tasks, task lists, goals, projects, and routines have SQLite-backed CRUD APIs.
- Active routines generate idempotent concrete task occurrences through the in-container scheduler, using `America/Chicago` by default.

- Source repository: `bcl1713/lifeos`
- Deployment repository: `bcl1713/homelab-stacks`
- Image registry: `ghcr.io/bcl1713/lifeos`
- Runtime target: private Docker/Portainer deployment on existing TrueNAS infrastructure
- Web UI: `/login`, `/`, and `/tasks` provide authenticated browser task operations.
- Recovery tooling: `python /app/scripts/backup_lifeos.py` creates an online SQLite backup in `/backups`; `python /app/scripts/verify_backup.py /backups/<file>.db` validates integrity and required tables.
- Wiki provenance validation: `python scripts/validate_wiki_provenance.py /home/brian/wiki` checks opted-in frontmatter/provenance metadata and reports bounded legacy-note warnings.
- Phase 5 workflow validation: `python scripts/validate_phase5_workflows.py /home/brian/wiki` checks the canonical capture/retrieval contract.
- Phase 6 memory validation: `python scripts/validate_phase6_memory.py /home/brian/wiki` checks persistent-memory routing and wiki-rule presence.

## Local development

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[test]'
pytest -q
uvicorn lifeos.main:app --reload
```

The development health endpoint is available at `http://127.0.0.1:8000/healthz`.

## Release model

Releases use semantic-version tags in the form `vMAJOR.MINOR.PATCH`. A tag such as `v0.1.0` runs the release workflow, builds the production image, and publishes it to GHCR as both the version tag and immutable commit SHA tag. Production deployment must use an explicit version tag or digest, never `latest`.

## Boundaries

- Durable context remains in `/home/brian/wiki`.
- Active task state will be authoritative in LifeOS after the verified Google Tasks migration and cutover.
- Secrets never belong in this repository.
- Production deployment configuration belongs in `bcl1713/homelab-stacks`, not here.
