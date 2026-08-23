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

- `/home/brian/wiki`: canonical, structured, human-readable source for active Projects, Areas, Tasks, relationships, durable narrative, and relevant history. Goals and Routines are retired and must not be rewritten through the retirement report.
- LifeOS: authenticated portal/editor for the active wiki domains. Its database may contain a rebuildable parsed/index representation and execution projections for search, completion calculations, and audit queries, but it is not a competing writable authority.
- Bidirectional contract: active LifeOS mutations serialize to canonical wiki Markdown; active wiki changes are parsed back into LifeOS. Stable typed IDs prevent duplicate records regardless of entry point.
- Google Tasks: migration source until verified cutover, then historical reference only.

The durable model is therefore **Markdown-backed and database-assisted**. LifeOS and the wiki are two interfaces to the same active Project, Area, and Task content, not separate stores. Retired Goal and Routine projections are inventory-only; see [`goals-routines-retirement.md`](goals-routines-retirement.md).

## Mutation and recovery contract

1. Resolve the canonical record by stable wiki ID and validated relative path.
2. Require the caller's last-seen canonical `expected_hash` for updates.
3. Write canonical Markdown source-first with an atomic replacement.
4. If the source hash changed, return HTTP `409`; never overwrite an external wiki edit silently.
5. Refresh the SQLite projection from the canonical record only after the source write succeeds.
6. If projection refresh fails after a source write, report reconciliation-needed state. Rolling back SQLite cannot roll back the filesystem.

Tasks—including dependencies, parentage, recurrence/occurrence identity, status, and completion state—follow the same contract as Projects, Areas, Goals, and Routines. SQLite rows use local integer keys only for query efficiency; durable relationships are serialized with stable wiki IDs and rebuilt in a second pass independent of discovery order.

`scripts/sync_wiki_projection.py --check` is the non-mutating reconciliation gate. It reports missing and orphaned projections, duplicate identities and paths, stale hashes, type/path conflicts, missing identities, and invalid source links. A writable sync must refuse ambiguous canonical identities before mutating SQLite.
