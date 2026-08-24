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

## Task descriptive-content contract

For Task create and update requests, the optional API `notes` input is persisted
as the terminal canonical Markdown `## Summary` body. The canonical Summary body
is the durable authority for task descriptive prose; it is not mirrored into a
second writable notes field in new canonical task records. Task API reads,
projection rebuilds, and Task detail rendering all derive the displayed notes
from that same canonical content.

The entire body following `## Summary` belongs to the Task's descriptive prose.
It may include Markdown structure, including nested level-two headings, and must
survive a projection rebuild unchanged. Missing, empty, or whitespace-only API
notes do not create an empty `## Summary` placeholder.

Older canonical Task records that store `notes` in frontmatter remain readable as
a compatibility fallback. This is a read-compatibility rule, not authorization
for a bulk rewrite of existing wiki records; normal reconciliation does not need
to rewrite legacy records merely to make their notes visible.

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

## PARA task ownership and placement

Every active canonical Task has one explicit owner: `project` with a canonical
Project `owner_wiki_id`, `area` with a canonical Area `owner_wiki_id`, or `inbox`
with no owner ID and the `Inbox` task list. The source-first creation path rejects
any other combination. Project and Area tasks are placed in their owner's `tasks/`
directory; Inbox tasks are placed in `00-Inbox/tasks/`. The canonical path is kept
as `wiki_path` and is shown in Today and Tasks. A valid, safe resolved path gets
an **Open canonical task source** action. When
`LIFEOS_SILVERBULLET_BASE_URL` is unset, that action uses LifeOS's authenticated
source rendering; when an operator has verified and configured the base for the
same canonical wiki, the safe resolved action targets the URL-encoded canonical
Task destination at that SilverBullet base. Unavailable or unsafe paths remain plain
text so the task views continue to render.

Ordinary updates preserve the canonical path. Owner changes return HTTP `409` and
require the dry-run-first controlled-relocation workflow in
`docs/task-relocation-operations.md`. Reconciliation reports invalid ownership as
`invalid_task_owners` and writable sync refuses it before projection mutation.
Daily-capture scanning and approval are separate review inputs, not a competing
task store or an implicit creation path. The complete user, operator, and bounded
default-profile alignment contract is in
[`para-task-workflow.md`](para-task-workflow.md).
