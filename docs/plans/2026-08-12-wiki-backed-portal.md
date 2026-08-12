# Wiki-Backed LifeOS Portal Implementation Plan

> **For LifeOS:** Implement this plan in vertical slices. The wiki is the canonical content store; LifeOS is a portal/editor over that store, not a competing writable database.

**Goal:** Make LifeOS and `/home/brian/wiki` two interchangeable interfaces to the same Projects, Areas, Goals, Routines, and Tasks, with bidirectional parsing, editing, and verified read-back.

**Architecture:** Markdown in the existing PARA wiki remains the durable source of truth. LifeOS maintains only a rebuildable parsed/index representation plus execution-oriented projections where necessary for scheduling and query performance. Every LifeOS mutation serializes back to the canonical wiki; every wiki change is discoverable and importable without creating duplicates.

**Scope:** Projects, Areas, Goals, Routines, Tasks, relationships, lifecycle state, and relevant history. Preserve the existing wiki structure, links, provenance, authentication, backups, and private deployment boundary.

**Out of scope until separately approved:** destructive corpus rewrites, replacing SilverBullet, changing Google Tasks historical archives, broad PARA reorganization, or making the wiki database-hosted.

---

## Product contract

- One domain record has one stable identity, regardless of which interface created or edited it.
- Creating a Project, Area, Goal, Routine, or Task in LifeOS creates or updates the canonical wiki representation.
- Creating or editing the same record in the wiki makes the change visible in LifeOS after sync, and eventually through a documented automatic or explicit refresh boundary.
- LifeOS may cache parsed records and maintain derived execution indexes, but those stores are rebuildable and never become a second durable content authority.
- Human-readable Markdown remains usable directly in the wiki; structured frontmatter and predictable sections make it safely parsable and writable.
- Conflicts, malformed records, unresolved links, and stale indexes are visible and actionable. They are never silently discarded.

## Canonical content model

Define and document a versioned Markdown contract for:

- `project`: finite outcome, status, owner, scope, non-goals, risks, deadline, review trigger, goals, areas, tasks, and links;
- `area`: ongoing responsibility/domain, status, goals, projects, routines, and links;
- `goal`: outcome, baseline, target, rationale, constraints, review cadence/date, milestones, status, and supporting projects/routines;
- `routine`: cadence, schedule, target area/goal, task template, pause/skip policy, and operational metadata;
- `task`: stable ID, title, status, due date, recurrence/source metadata, parent/project/goal/area links, and completion history or a canonical history link.

Use stable typed IDs (`prj-`, `area-`, `goal-`, `rtn-`, `tsk-`), explicit `schema_version`, ISO dates, canonical relative paths, and wikilinks/IDs for relationships. Keep narrative sections separate from generated/index sections so serializers do not destroy prose.

## Phase 0 — Record the corrected intent and freeze the boundary

**Files:**
- Modify: `/home/brian/wiki/01-Projects/LifeOS/index.md`
- Modify: `docs/architecture.md`
- Modify: `README.md`
- Create: this plan

**Work:** Replace the obsolete claim that the LifeOS database owns structured life data. Record the wiki-backed portal contract, the rebuildable-index boundary, and the distinction between durable content and derived execution projections.

**Acceptance:** Documentation consistently states that wiki and LifeOS are two interfaces to one content model; no document claims that Projects/Areas/Goals/Routines are independently authoritative in SQLite.

## Phase 1 — Inventory the live wiki and current LifeOS records

**Files:**
- Create: `scripts/audit_wiki_lifeos_alignment.py`
- Create: `tests/test_wiki_lifeos_alignment.py`
- Inspect: `scripts/sync_wiki_context.py`, `src/lifeos/domain.py`, API routers, UI routes, existing migrations
- Inspect: `/home/brian/wiki/01-Projects/index.md`, `/home/brian/wiki/02-Areas/index.md`, all linked canonical notes

**Work:** Produce a read-only report that discovers canonical index entries, resolves case-insensitive `index.md`/`Index.md` paths, identifies nested/index exceptions, inventories LifeOS rows, and reports missing, duplicate, ambiguous, and unlinked records without mutating anything.

**Acceptance:** The report gives exact counts and paths for wiki Projects/Areas and LifeOS Projects/Goals/Routines, identifies the current mismatch, and has fixture coverage for all discovered path forms.

## Phase 2 — Implement the canonical Markdown parser and serializer

**Files:**
- Create: `src/lifeos/wiki_contract.py`
- Create: `tests/test_wiki_contract.py`
- Create: `tests/fixtures/wiki_contract/`

**Work:** Parse frontmatter, stable IDs, typed values, relationships, canonical sections, and preserved prose. Serialize supported changes with minimal diffs, preserving unknown frontmatter, Markdown sections, wikilinks, dates, and comments where possible. Reject unsafe paths and malformed identity fields.

**Acceptance:** Round-trip tests prove parse → serialize → parse stability, preservation of human content, stable IDs, relationship handling, malformed-data errors, and path-traversal protection.

## Phase 3 — Replace heuristic discovery with canonical wiki indexing

**Files:**
- Modify: `scripts/sync_wiki_context.py`
- Modify: `src/lifeos/domain.py` and migration only if derived-index fields require it
- Modify: `src/lifeos/wiki_context_api.py`
- Modify: `tests/test_wiki_context.py`

**Work:** Discover top-level canonical records from the Projects and Areas index pages, resolve both filename cases and wikilinks, include all explicitly linked records, preserve unresolved/stale entries as warnings, and make sync idempotent by stable ID/path/content hash.

**Acceptance:** A temporary wiki with mixed-case filenames, nested folders, linked records, missing targets, and archived/unlinked notes produces the expected report; repeated sync creates no duplicates; missing records become visible stale/unresolved entries.

## Phase 4 — Make Projects, Areas, Goals, and Routines wiki-backed

**Files:**
- Modify: `src/lifeos/api.py` and relevant domain routers
- Modify: `src/lifeos/ui.py`
- Modify: `src/lifeos/templates/base.html`, `context.html`, `wiki_context.html`, and domain templates
- Create/modify: `tests/test_wiki_backed_crud.py`

**Work:** Route create/update/archive operations through a shared wiki repository service. LifeOS creates canonical notes when requested, edits existing notes by stable ID, refreshes the derived index, and displays the canonical wiki path on every record. Remove the ambiguous Context/Projects split; use clear Wiki, Areas, Projects, Goals, and Routines views over the same records.

**Acceptance:** Authenticated browser/API tests create and edit each record in LifeOS, read the resulting Markdown from the wiki, then read it back through LifeOS. The reverse path edits Markdown and verifies LifeOS reflects the change after sync.

## Phase 5 — Establish task and routine execution projections

**Files:**
- Modify: task/routine models, scheduler, generation services, and migrations as required
- Modify: `scripts/export_lifeos.py`, backup/restore verification
- Create/modify: focused task/routine projection tests

**Work:** Keep task execution, generated occurrences, completion history, and audit data efficient for LifeOS while defining their canonical wiki representation and sync rules. Ensure generated operational records do not overwrite human-authored content or create duplicate task instances.

**Acceptance:** Routine generation is idempotent; task completion writes canonical state and history; rebuilding the execution projection from wiki fixtures produces equivalent active state; backup/restore preserves both canonical-content references and execution history.

## Phase 6 — Reconcile existing data and remove duplicate authority

**Files:**
- Create: `scripts/reconcile_wiki_lifeos.py`
- Create: `scripts/migrate_lifeos_to_wiki.py` or an explicitly named replacement
- Create: migration/reconciliation report under the LifeOS wiki project
- Modify: `tests/test_reconciliation.py`

**Work:** Take verified backups. Map existing SQLite Projects/Goals/Routines and wiki notes by stable IDs, canonical paths, aliases, and reviewed title matches. Require explicit handling for conflicts. Write only approved canonical records to the wiki, preserve provenance, mark migrated database rows as projections, and prohibit parallel writes during cutover.

**Acceptance:** Staging rehearsal reconciles counts and representative samples; every conflict has a disposition; pre/post backups verify; repeated migration is idempotent; no source record is silently deleted.

## Phase 7 — Runtime synchronization and conflict handling

**Files:**
- Modify: application startup/scheduler and API services
- Create: `src/lifeos/wiki_sync.py`
- Create: `tests/test_wiki_sync.py`
- Modify: deployment compose/mount documentation in the deployment repository

**Work:** Integrate the real read-only or read-write wiki mount boundary deliberately. Add explicit sync/refresh status, content hashes, last indexed time, conflict detection, and safe failure behavior. Do not claim end-to-end integration until the deployed service can read and write a real mounted wiki file.

**Acceptance:** Live staging tests prove wiki edit → LifeOS refresh and LifeOS edit → wiki read-back, with conflict detection and no lost updates. Production remains read-only until the write path and backup/recovery gates pass.

## Phase 8 — UI, agent, and operational workflow cleanup

**Files:**
- Modify: all affected templates and API documentation
- Modify: Hermes LifeOS-related skills/prompts only after the application contract is stable
- Modify: `docs/operations.md`, `docs/architecture.md`, `README.md`
- Create: `docs/wiki-portal-usage.md`

**Work:** Explain the interaction model in the product: Wiki is the canonical content store; LifeOS is the portal. Remove “Context” ambiguity, expose canonical paths, show sync/conflict status, and document when to use either interface. Audit scheduled prompts and scripts for stale assumptions about separate writable project/context stores.

**Acceptance:** A new user can create, edit, locate, and reconcile a Project, Area, Goal, Routine, and Task from either interface without being told to maintain duplicate records.

## Phase 9 — Full verification and cutover

**Files:**
- Modify/create focused validators and release evidence in `scripts/`
- Modify: canonical LifeOS project acceptance record

**Verification:**

```bash
uv run pytest -q
uv run ruff check .
uv run python scripts/audit_wiki_lifeos_alignment.py --wiki /home/brian/wiki --database <staging-db>
uv run python scripts/validate_project_intent.py .
```

Then, separately verify:

- clean migration upgrade and downgrade/re-upgrade;
- backup and restore of the application projection and canonical wiki files;
- authenticated browser create/edit/read-back in both directions;
- authenticated agent create/edit/read-back in both directions;
- production bind mount and file permissions;
- no duplicate writers or stale scheduled workflows;
- live version, image, mount, health, and revision;
- temporary smoke records archived or removed.

Do not mark the project intent complete merely because the application release is green. The acceptance record must show measured bidirectional evidence.

## Migration and safety rules

- Take and verify a pre-change backup before reconciliation or deployment.
- Never silently choose between conflicting wiki and SQLite values.
- Preserve legacy notes and unknown Markdown; migrate opportunistically or report bounded warnings.
- Do not expose wiki contents outside the private deployment boundary.
- Do not permit simultaneous uncoordinated writers during cutover.
- Keep the database projection rebuildable and document the rebuild command.
- If the deployed wiki mount is unavailable, fail visibly and preserve the last known index; do not overwrite canonical content with empty data.
