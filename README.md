# LifeOS

Private life operating system for tasks, routines, goals, projects, reviews, and selected life data.

## Status

Authenticated portal and workflow interface over the canonical LifeOS wiki.

- `/healthz` is public.
- `/auth/login`, `/auth/logout`, `/auth/me`, and agent bearer authentication are available.
- Tasks, Projects, Areas, Goals, and Routines are canonical Markdown records in `/home/brian/wiki`.
- LifeOS APIs and browser workflows write canonical Markdown source-first, then refresh rebuildable SQLite projections used for querying, scheduling, and display.
- Active routines generate idempotent concrete Task occurrences through the in-container scheduler, using `America/Chicago` by default; generated occurrences are also canonical wiki records.

- Source repository: `bcl1713/lifeos`
- Deployment repository: `bcl1713/homelab-stacks`
- Image registry: `ghcr.io/bcl1713/lifeos`
- Runtime target: private Docker/Portainer deployment on existing TrueNAS infrastructure
- Web UI: `/login`, `/`, and `/tasks` provide authenticated browser task operations.
- Recovery tooling: `python /app/scripts/backup_lifeos.py` creates an online SQLite backup in `/backups`; `python /app/scripts/verify_backup.py /backups/<file>.db` validates integrity and required tables.
- Wiki provenance validation: `python scripts/validate_wiki_provenance.py /home/brian/wiki` checks opted-in frontmatter/provenance metadata and reports bounded legacy-note warnings.
- Phase 5 workflow validation: `python scripts/validate_phase5_workflows.py /home/brian/wiki` checks the canonical capture/retrieval contract.
- Phase 6 memory validation: `python scripts/validate_phase6_memory.py /home/brian/wiki` checks persistent-memory routing and wiki-rule presence.
- Phase 7 skill validation: `python scripts/validate_phase7_skills.py ~/.hermes/skills` checks the six required LifeOS skills and their contract sections.
- Phase 8 deployment validation: `python scripts/validate_phase8_deployment.py .` checks the private application repository, recovery tooling, image/health contract, and runtime identity pattern.
- Phase 9 cutover validation: `python scripts/validate_phase9_cutover.py /home/brian/wiki ~/.hermes/cron` checks LifeOS task authority and rejects scheduled Google Tasks writers.
- Phase 10 test validation: `python scripts/validate_phase10_tests.py .` checks the required focused test matrix, recovery artifacts, and source secret hygiene.
- Whole-project intent validation: `python scripts/validate_project_intent.py .` checks promised deliverables and current operator documentation against the stated LifeOS intent.
- Wiki-backed portal architecture: `docs/architecture.md` and `docs/plans/2026-08-12-wiki-backed-portal.md` define the canonical Markdown contract, bidirectional LifeOS/wiki editing model, staged reconciliation, and cutover verification. LifeOS is not a second writable knowledge base.
- Rendered canonical source navigation: `docs/rendered-source-navigation.md` documents the authenticated Project/Area source affordance, safe in-wiki navigation, and optional SilverBullet canonical-link configuration.
- Wiki projection sync: `python scripts/sync_wiki_projection.py --database sqlite:///./data/lifeos.db --wiki-root /wiki` rebuilds typed Task, Project, Area, Goal, and Routine projections from canonical wiki Markdown. Add `--check` for non-mutating reconciliation of missing, orphaned, duplicate, stale-hash, type/path-conflict, and invalid-link records.
- Updates require the caller's last-seen canonical `expected_hash`; an external wiki edit produces HTTP `409` rather than a silent overwrite.

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

The package version is the `[project].version` value in `pyproject.toml`. Release artifacts are immutable and always use an explicit version or `sha-<commit>` tag; production deployment must use an explicit version tag or digest, never `latest`.

- A successful push or merge to `dev` first runs verification, tests, and the package build. Only after those checks pass does it publish the unique candidate `v<next-patch>-dev.<GitHub-run-number>` and `sha-<commit>` tags to `ghcr.io/bcl1713/lifeos` and create a GitHub prerelease. The candidate's patch number is one greater than `[project].version`.
- Pull-request pushes and failed checks publish no image or release. This workflow does not publish a mutable `dev` convenience tag, `latest`, a stable tag, or perform an automatic deployment or production promotion.
- RC publication remains a manual dispatch from `dev` with an explicit `vMAJOR.MINOR.PATCH-rc.N` version. Stable `vMAJOR.MINOR.PATCH` releases remain `main`-only, after Brian approves the `dev` → `main` release gate.

Run `python scripts/validate_release_policy.py --repository .` to check the release workflow controls. After publication, verify the GitHub Release and resolve both the candidate/version tag and its `sha-<commit>` tag to the same image digest before testing or promotion. Deployment configuration and rollout remain separate, explicit changes in `bcl1713/homelab-stacks`.

## Boundaries

- `/home/brian/wiki` is the canonical durable authority for Task, Project, Area, Goal, and Routine identity, relationships, lifecycle state, recurrence identity, and completion state.
- SQLite is a disposable, rebuildable projection and audit/query cache. It must never be treated as a second writable domain authority.
- Every accepted domain mutation is source-first: canonical Markdown succeeds before projection state is committed.
- Google Tasks is read-only historical data and is not a writer or authority.
- Secrets never belong in this repository.
- Production deployment configuration belongs in `bcl1713/homelab-stacks`, not here.
