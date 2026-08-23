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

## Rendered canonical source navigation

Projects and Areas expose their canonical root-relative Markdown path and an
**Open canonical note** action. Without an external canonical-link base, the
action uses LifeOS's authenticated `/sources/wiki/...` route, which renders a
small escaped Markdown subset from the current canonical file. Supported
wikilinks and relative Markdown `.md` links in that route remain internal to
the authenticated LifeOS source view; invalid or unsafe targets are displayed
with diagnostics instead of links.

`LIFEOS_SILVERBULLET_BASE_URL` is optional. When configured, it changes the
Project/Area canonical-note action to a URL-encoded SilverBullet path; it does
not change rendered in-wiki navigation or make SilverBullet a LifeOS dependency.
The setting must point to the same canonical wiki content. See
`docs/rendered-source-navigation.md` for user behavior, safety boundaries, and
operator checks.

## Mutation and recovery contract

1. Resolve the canonical record by stable wiki ID and validated relative path.
2. Require the caller's last-seen canonical `expected_hash` for updates.
3. Write canonical Markdown source-first with an atomic replacement.
4. If the source hash changed, return HTTP `409`; never overwrite an external wiki edit silently.
5. Refresh the SQLite projection from the canonical record only after the source write succeeds.
6. If projection refresh fails after a source write, report reconciliation-needed state. Rolling back SQLite cannot roll back the filesystem.

Tasks—including dependencies, parentage, recurrence/occurrence identity, status, and completion state—follow the same contract as active Projects and Areas. SQLite rows use local integer keys only for query efficiency; durable relationships are serialized with stable wiki IDs and rebuilt in a second pass independent of discovery order. Retired Goal and Routine projections are excluded from active mutation and recurrence generation; their read-only inventory contract is in [`goals-routines-retirement.md`](goals-routines-retirement.md).

`scripts/sync_wiki_projection.py --check` is the non-mutating reconciliation gate. It reports missing and orphaned projections, duplicate identities and paths, stale hashes, type/path conflicts, missing identities, and invalid source links. A writable sync must refuse ambiguous canonical identities before mutating SQLite.

## Daily-capture scan boundary

`scripts/scan_daily_captures.py` is a review-only reader of an explicit daily-note
marker. It returns deterministic proposals and exceptions but creates no Task,
performs no canonical Markdown or projection write, and does not schedule promotion.
A human must route an approved proposal through the normal source-first mutation
contract. The exact grammar, JSON schema, duplicate/source-hash behavior, and
non-goals are documented in `docs/daily-capture-scan.md`.

## Controlled capture-promotion boundary

Implementation PR [#38](https://github.com/bcl1713/lifeos/pull/38) adds a reviewed,
fixture-only bridge from an unmodified scanner proposal to one owner-local canonical
Task. Its approval binds the complete scanner payload and canonical JSON fingerprint;
the exact scanner line hash and `{type, id, path}` target identity are revalidated
before any source write. The source-first task write is followed by an idempotent
daily-capture receipt. If projection or receipt work cannot complete after the source
write, the result is reconciliation required rather than a claimed rollback.

The same candidate produces deterministic canonical weekly/monthly review records with
source backlinks for scan, task, owner, and recognized reconciliation evidence. Its
fixture-root marker requirement is a test-only guard: no current or future invocation
of this contract authorizes `/wiki`, `/home/brian/wiki`, a default-profile asset, or a
real-wiki apply. The full operator contract is in
`docs/controlled-capture-promotion.md`.

## Planned task ownership and PARA placement

The following is the authoritative target contract for implementation PR [#27](https://github.com/bcl1713/lifeos/pull/27). It is prospective: it does not describe current `dev` behavior until that PR lands. Once implemented, each newly created canonical Task will have one explicit owner type:

- `project` with an `owner_wiki_id` that resolves to a canonical Project;
- `area` with an `owner_wiki_id` that resolves to a canonical Area; or
- `inbox`, which has no `owner_wiki_id` and is valid only for the `Inbox` task list.

The API will reject a new non-Inbox Task without a Project or Area owner, and will reject an Inbox owner paired with a non-Inbox task list or an owner ID. It will also reject an owner ID that does not resolve to the declared canonical type. These ownership fields will be serialized in canonical task Markdown and retained in the rebuildable Task projection.

Once #27 lands, creation will choose the canonical Markdown path deterministically. A Project or Area task will be a sibling beneath its owner's directory at `<owner-directory>/tasks/<slug>-<tsk-id>.md`; an Inbox task will be at `00-Inbox/tasks/<slug>-<tsk-id>.md`. For example, a task owned by `01-Projects/renovate-kitchen/index.md` will be written beneath `01-Projects/renovate-kitchen/tasks/`. The exact path will be retained as the task's `wiki_path` and shown as its source in the Tasks and Today views.

Once #27 lands, ordinary task edits will preserve the existing canonical path, even when the title changes. Changing `owner_type` or `owner_wiki_id` will deliberately not be an ordinary edit: the API will return `409` and require the separate controlled-relocation workflow from implementation PR [#31](https://github.com/bcl1713/lifeos/pull/31). That workflow is dry-run-first and requires an explicit later Brian gate before any real-wiki `--apply`; its complete operator contract is in `docs/task-relocation-operations.md`. It creates no owner-note backlinks and does not change daily-note promotion behavior. Source navigation remains the existing canonical-source behavior: `wiki_path` identifies the task source, and authenticated `/sources/wiki/...` rendering resolves links from that source; a separate `source_ref` remains task provenance metadata rather than an ownership backlink.

Once #27 lands, every canonical Task must satisfy one of those owner combinations, including legacy source records. A Task that lacks both owner fields is invalid unless it is explicitly Inbox (`owner_type: inbox`, no owner ID, and `task_list: Inbox`); it is not merely discoverable compatibility data. Reconciliation will report it as `invalid_task_owners`, and writable sync will refuse it before projection mutation. Google Tasks historical migration assigns Inbox ownership explicitly; it may retain an existing same-source canonical path only to avoid relocating that record. When canonicalizing a legacy projection, the tooling derives a Project owner when one exists; otherwise it permits only the Inbox combination and rejects non-Inbox rows. Goals and Routines are retired legacy projections; they have no active canonical workflow or scheduler behavior. See [`goals-routines-retirement.md`](goals-routines-retirement.md).
