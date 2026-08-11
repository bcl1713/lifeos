# LifeOS

Private life operating system for tasks, routines, goals, projects, reviews, and selected life data.

## Status

Initial application scaffold. The service currently exposes an authenticated deployment-ready health surface; domain and task persistence work follows the implementation plan in the wiki.

- Source repository: `bcl1713/lifeos`
- Deployment repository: `bcl1713/homelab-stacks`
- Image registry: `ghcr.io/bcl1713/lifeos`
- Runtime target: private Docker/Portainer deployment on existing TrueNAS infrastructure

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
