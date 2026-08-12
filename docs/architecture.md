# LifeOS architecture

## Initial deployment boundary

LifeOS is a private application container deployed by Portainer on the existing TrueNAS Docker host. Application source lives in the private `bcl1713/lifeos` repository. The Portainer deployment definition will live in `bcl1713/homelab-stacks` under `stacks/apps/lifeos/`.

## Initial runtime

- FastAPI application
- SQLite with WAL mode for the first persistence implementation
- Persistent application data mounted at `/data`
- Private proxy-network attachment
- Browser sessions and a separate agent credential
- GHCR images published from semantic-version tags

## Source-of-truth boundary

- `/home/brian/wiki`: canonical, structured, human-readable source for Projects, Areas, Goals, Routines, Tasks, relationships, durable narrative, and relevant history.
- LifeOS: authenticated portal/editor for the wiki. Its database may contain a rebuildable parsed/index representation and execution projections for scheduling, search, completion calculations, and audit queries, but it is not a competing writable authority.
- Bidirectional contract: LifeOS mutations serialize to canonical wiki Markdown; wiki changes are parsed back into LifeOS. Stable typed IDs prevent duplicate records regardless of entry point.
- Google Tasks: migration source until verified cutover, then historical reference only.

The durable model is therefore **Markdown-backed and database-assisted**. LifeOS and the wiki are two interfaces to the same content, not separate stores of Projects, Areas, Goals, or Routines. See `docs/plans/2026-08-12-wiki-backed-portal.md` for the staged migration plan.

## Mutation and recovery contract

1. Resolve the canonical record by stable wiki ID and validated relative path.
2. Require the caller's last-seen canonical `expected_hash` for updates.
3. Write canonical Markdown source-first with an atomic replacement.
4. If the source hash changed, return HTTP `409`; never overwrite an external wiki edit silently.
5. Refresh the SQLite projection from the canonical record only after the source write succeeds.
6. If projection refresh fails after a source write, report reconciliation-needed state. Rolling back SQLite cannot roll back the filesystem.

Tasks—including dependencies, parentage, recurrence/occurrence identity, status, and completion state—follow the same contract as Projects, Areas, Goals, and Routines. SQLite rows use local integer keys only for query efficiency; durable relationships are serialized with stable wiki IDs and rebuilt in a second pass independent of discovery order.

`scripts/sync_wiki_projection.py --check` is the non-mutating reconciliation gate. It reports missing and orphaned projections, duplicate identities and paths, stale hashes, type/path conflicts, missing identities, and invalid source links. A writable sync must refuse ambiguous canonical identities before mutating SQLite.
