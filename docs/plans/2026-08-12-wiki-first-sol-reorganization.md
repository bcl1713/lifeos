# Wiki-First SOL Reorganization Plan

> **For Hermes:** Use the SOL model for this plan and implementation. Treat this document as the controlling project contract until superseded by a newer accepted plan.

**Goal:** Make LifeOS a single usable authenticated interface over the existing `/home/brian/wiki`, with no competing domain catalogue, no separate Wiki product area, no independently authoritative Task/Project/Area/Goal/Routine records, and no broken source links.

**Architecture:** The wiki remains the canonical durable record and navigation graph for Tasks, Projects, Areas, Goals, and Routines. LifeOS becomes a projection, query, workflow, scheduling, and authenticated write interface over that graph; its SQLite tables are rebuildable indexes, materialized execution views, and audit caches only. The primary UI is organized by workflow—Today, Projects, Areas, Tasks, Goals, Routines, Data—not by exposing a second “Wiki” product. Every domain record resolves to verified canonical Markdown or a clearly reported missing-source state; LifeOS never emits an untested URL or accepts a projection-only mutation as durable truth.

**Tech Stack:** FastAPI, Jinja server-rendered UI, SQLAlchemy/SQLite projections, Markdown/YAML wiki records, pytest, Docker, Git-backed Portainer deployment.

---

## 1. Problem statement and non-negotiable decisions

The current release is not usable because it violates its own intended model in three visible ways:

1. Projects appear in both the LifeOS Projects view and a separate Wiki/Context view.
2. The Wiki/Context view is a catalogue rather than the canonical Project/Area workflow, so it feels like a second product.
3. Wiki links are generated without a verified resolution contract and are broken in the deployed view.

The following decisions are binding for implementation:

- `/home/brian/wiki` is the only durable source for Tasks, Projects, Areas, Goals, Routines, and other contextual records.
- PARA remains intact: `01-Projects`, `02-Areas`, `03-Research`, `04-Archives`, `dailies`, `assets`, and `templates`.
- A Project is identified by its canonical wiki path and stable wiki ID, not by a separately created LifeOS row.
- An Area is identified by its canonical wiki path and stable wiki ID, not by a separately created LifeOS row.
- Goals and Routines are canonical wiki records with explicit Project/Area relationships; their SQLite forms are rebuildable projections only.
- Tasks, including status, due date, recurrence identity, dependencies, completion state, and archive state, are canonical wiki records. LifeOS may materialize execution views and an append-only audit cache, but every accepted mutation must persist canonical Markdown first and be recoverable from the wiki.
- SQLite projections may cache title, status, summary, relationships, links, hashes, scheduling indexes, and query-optimized state. They must be rebuildable from the wiki and must never be presented as a durable domain store.
- The UI has one Project view and one Area view. There is no top-level “Wiki” or “Context” navigation item.
- “Open source” links must point to the actual SilverBullet/wiki URL or a verified internal source route. Every emitted link must pass a resolver test.
- Missing or ambiguous links are visible and actionable; they are not silently rendered as dead anchors.
- New or changed behavior is not accepted from a green unit suite alone. It requires projection reconciliation, link-resolution tests, authenticated live read-back, backup/recovery evidence, and browser verification.

## 2. SOL operating model

For this project, SOL means a source-oriented lifecycle:

- **S — Source:** identify the canonical wiki record, path, ID, aliases, and current content hash before designing or changing a LifeOS representation.
- **O — Operations:** expose workflows over that source—browse, search, inspect, edit through the approved write path, link tasks, and complete operational work—without creating a parallel conceptual area.
- **L — Loop:** rebuild projections, reconcile drift, detect conflicts, verify links, test authenticated behavior, and read back the persisted source after every consequential change.

Every implementation task must answer:

1. What is the canonical source file and stable identity?
2. Which canonical Markdown field owns this value, and which SQLite fields are rebuildable derivatives?
3. Which single UI workflow owns the record?
4. How is the source link resolved and tested?
5. How are drift, missing records, stale hashes, and recovery handled?

## 3. Current-state audit to preserve in the implementation record

The audit that motivated this plan found:

- `src/lifeos/src/lifeos/templates/base.html` exposes both `Wiki` and `Projects` navigation.
- `src/lifeos/src/lifeos/templates/wiki_context.html` renders Projects and Areas as a separate read-only catalogue.
- `/projects` remains a separate LifeOS project workflow and currently creates/updates projection records.
- `scripts/sync_wiki_context.py` discovers canonical top-level category index entries but does not establish a complete, verified URL contract for browser links.
- `WikiContextItem.wiki_url` is passed directly to HTML without a resolver/read-back test.
- `WikiRepository._path()` creates typed records under a LifeOS-specific subtree for goals, routines, and tasks; this path must be reconciled with the canonical PARA model before further writes are enabled.
- The live production mount and local wiki checkout do not currently report identical Project/Area sets. This is a data-source/deployment reconciliation issue and must be made visible rather than hidden.

These are findings, not acceptance claims. They must be rechecked after implementation.

## 4. Target information architecture

### Primary navigation

The authenticated header must contain only workflow surfaces:

- Today
- Projects
- Areas
- Tasks
- Goals
- Routines
- Data
- Log out

Remove `Wiki` and `Context` from primary navigation. A source-link affordance may say “Open canonical note” or “View in wiki,” but the wiki is not a competing LifeOS section.

### Projects

`/projects` is the canonical Project view. It must:

- list all non-stale canonical Project records discovered from the wiki;
- group active, paused, completed, and archived records explicitly;
- show title, status, summary, next action, and linked Area/Goal where present;
- show task counts from operational LifeOS data without copying task state into wiki prose;
- provide a verified canonical-note link;
- expose source path, stable ID, and last-seen/hash diagnostics only in an optional details area;
- distinguish “no link,” “ambiguous link,” and “source unavailable” from a valid link;
- never create a second Project record merely because a Project is absent from the projection.

### Areas

Add `/areas` as the canonical Area view, using the same source/projection contract as Projects. Areas are ongoing responsibilities and specialist domains, not generic LifeOS containers. Preserve House, People, Medical, Education, Personal Finance, Work, Personal, and other existing Areas.

### Detail views

Add source-backed detail routes:

- `/projects/{wiki_id}`
- `/areas/{wiki_id}`

These routes must resolve the current canonical wiki record by stable ID, show its current metadata and summary, list linked operational tasks/goals/routines, and provide conflict-aware write actions only where the record type and deployment permissions permit.

### Today and workflow surfaces

Today and Tasks remain workflow-first views over canonical task Markdown. Completing, rescheduling, pausing, cancelling, archiving, generating, or linking a task must update the canonical task record through the shared repository service with optimistic conflict detection, then refresh the projection. Checkbox syntax embedded in unrelated prose is not the task contract; typed task notes are.

## 5. Canonical record and projection contract

Create one explicit contract module and test fixture set:

- `wiki_id`: stable canonical identity from frontmatter or deterministic migration identity.
- `wiki_path`: root-relative Markdown path under `/home/brian/wiki`.
- `wiki_hash`: SHA-256 of the exact persisted source text last read.
- `source_type`: `project`, `area`, `goal`, `routine`, or `task`.
- `canonical_url`: verified external SilverBullet URL or verified internal source route.
- `link_status`: `valid`, `missing`, `ambiguous`, `unavailable`, or `not_configured`.
- `projection_status`: `current`, `stale`, `orphaned`, `conflict`, or `unindexed`.

The projection reconciler must produce a deterministic report containing:

- source records discovered;
- projection records matched by stable ID;
- missing projections;
- orphaned projections;
- duplicate IDs/paths;
- stale hashes;
- invalid or unresolved links;
- records whose source type or canonical path changed.

No reconciler command may mutate the wiki. Projection rebuild must be separately invoked and idempotent. Writes must use optimistic hash checks and return `409` on stale source content.

## 6. Link-resolution contract

Implement a single resolver, used by API and HTML rendering:

1. Normalize the root-relative wiki path.
2. Reject traversal and absolute filesystem paths.
3. Confirm the target exists under the configured wiki root when the deployment mount is available.
4. Confirm the target is a Markdown canonical record where required.
5. Generate the configured SilverBullet URL using a single documented encoding rule, or generate an authenticated internal source route when external SilverBullet linking is unavailable.
6. Return structured link status and diagnostic reason.

The UI must never render `href` directly from an unvalidated raw field. Tests must cover:

- spaces, punctuation, mixed-case `Index.md`, and nested paths;
- URL encoding;
- missing source files;
- traversal attempts;
- production `/wiki` read-only mounts;
- SilverBullet URL configuration;
- fallback internal route behavior.

## 7. Migration and reconciliation sequence

### Task 1: Freeze the current boundary

**Files:**
- Modify: `docs/architecture.md`
- Modify: `README.md`
- Modify: `docs/operations.md`
- Modify: `/home/brian/wiki/agent_rules.md` only if the canonical rules need correction
- Modify: this plan only for measured findings

Write the target boundary plainly: wiki-backed Tasks, Projects, Areas, Goals, and Routines are one model; SQLite is a rebuildable projection/materialized execution view. Remove contradictory language claiming that LifeOS owns durable domain records.

**Verification:** documentation validator fails on `Wiki`/`Context` as a primary product concept or on duplicate authority language, then passes after correction.

### Task 2: Add canonical source/link resolver tests first

**Files:**
- Create: `src/lifeos/src/lifeos/wiki_links.py`
- Create: `tests/test_wiki_links.py`
- Modify: `src/lifeos/src/lifeos/source_api.py`

Write failing tests for valid, missing, ambiguous, traversal, and encoded canonical links. Implement one resolver used by API and templates.

**Verification:** `pytest -q tests/test_wiki_links.py` passes and no template can emit an unvalidated `wiki_url`.

### Task 3: Reconcile discovery with actual PARA indexes

**Files:**
- Modify: `scripts/sync_wiki_context.py`
- Modify: `src/lifeos/src/lifeos/wiki_store.py`
- Modify: `tests/test_wiki_context.py`
- Create: `tests/fixtures/wiki_reconciliation/`

Discover Project and Area records from the canonical category indexes, resolve their actual paths, preserve mixed-case filenames, detect duplicate IDs and broken index links, and report all discrepancies. Do not use a broad recursive scan as the authority.

**Verification:** run against a fixture with valid, broken, duplicate, and mixed-case links; run against local `/home/brian/wiki`; compare the report with the production report rather than claiming the counts are interchangeable.

### Task 4: Replace Wiki/Context with unified Project and Area views

**Files:**
- Modify: `src/lifeos/src/lifeos/templates/base.html`
- Delete or repurpose: `src/lifeos/src/lifeos/templates/wiki_context.html`
- Modify: `src/lifeos/src/lifeos/ui.py`
- Modify: `src/lifeos/src/lifeos/context_api.py`
- Create/modify: Project and Area templates and detail routes
- Create: `tests/test_unified_navigation.py`

Remove the `Wiki` navigation item. Make `/projects` and `/areas` read from the same canonical projection service. Keep source links as an affordance inside the record view. There must be no second list with the same Project cards under a different label.

**Verification:** HTML assertions show exactly one Project navigation/list surface and one Area navigation/list surface; `/context` either redirects permanently to `/projects`/`/areas` or returns a deliberate deprecation response.

### Task 5: Stop accidental duplicate writes

**Files:**
- Modify: `src/lifeos/src/lifeos/context_api.py`
- Modify: `src/lifeos/src/lifeos/area_api.py`
- Modify: `src/lifeos/src/lifeos/scripts_bridge.py`
- Modify: `src/lifeos/src/lifeos/domain.py`
- Modify: CRUD tests for Projects, Areas, Goals, and Routines

For an existing wiki-backed record, update the canonical source by `wiki_id` and `wiki_path` with `expected_hash`. For a new record, require an explicit canonical destination rule and write it once to the wiki before creating/updating the projection. Never create a LifeOS-native duplicate because a projection is missing or stale.

Define and document canonical PARA placement for Tasks, Goals, and Routines. Add canonical wiki paths and use the same source contract for all five domain types.

**Verification:** create/update/read-back tests prove one source file and one projection identity; stale hashes return `409`; reconciliation reports no duplicate canonical IDs.

### Task 6: Add usable search and source diagnostics

**Files:**
- Modify: Project/Area API and templates
- Create: `tests/test_project_area_search.py`
- Modify: `docs/operations.md`

Add title/alias/path search, active/archived filters, source status, and an actionable “repair link”/“source unavailable” diagnostic. Do not expose hashes and filesystem details in the primary workflow by default.

**Verification:** authenticated browser tests cover search, filters, empty state, valid links, broken-link diagnostics, and mobile layout.

### Task 7: Repair the real wiki navigation

**Files:**
- Modify only the smallest canonical set under `/home/brian/wiki/01-Projects/index.md`, `/home/brian/wiki/02-Areas/index.md`, and affected canonical notes
- Create: `scripts/validate_wiki_links.py`
- Create: `tests/test_validate_wiki_links.py`

Audit every Project/Area index link used by LifeOS. Correct links to actual relative Markdown paths, preserve aliases and existing note names, and do not flatten the PARA tree. Validate both local wiki and the production-mounted dataset when available.

**Verification:** validator reports zero broken canonical Project/Area links for the selected acceptance set; all changed wiki files are read back and their links resolve.

### Task 8: Rebuild projection and prove recovery

**Files:**
- Modify: `scripts/sync_wiki_projection.py`
- Modify: `scripts/audit_wiki_lifeos_alignment.py`
- Modify: `docs/operations.md`
- Modify: deployment README/compose only if startup behavior changes

Make startup sync produce a concise auditable report. Add a safe `--check` reconciliation mode and a documented backup/restore rehearsal. A deployment is not accepted if it reports green while source/projection/link reconciliation is non-zero without an explicit waiver.

**Verification:** fresh SQLite rebuild from the production wiki produces the same canonical record counts and IDs as the live projection; backup restore passes integrity and representative read-back.

### Task 9: Live rollout through Portainer

**Files:**
- Modify: `src/lifeos` release metadata
- Modify: `src/homelab-stacks/stacks/apps/lifeos/README.md` only for measured deployment evidence

Before deployment:

- run focused and full tests;
- run wiki link and projection reconciliation;
- build the immutable image;
- create and verify a pre-deploy backup;
- record the expected local and production source counts separately.

Deploy through the Git-backed Portainer stack using the established recreate/update procedure. Preserve `/data`, `/backups`, secrets, proxy network, and scheduler settings; transition `/wiki` from read-only to writable only after a verified wiki backup, container write-permission rehearsal, conflict tests, and rollback evidence.

After deployment:

- verify image/version and health;
- inspect startup migration/sync logs;
- verify `/projects`, `/areas`, `/tasks`, and source-backed detail views through authenticated browser/API paths;
- verify at least one valid link and one deliberately diagnosed missing link;
- run a post-deploy backup and integrity check;
- read back the canonical wiki and projection report.

### Task 10: Acceptance and cleanup

**Files:**
- Modify: `/home/brian/wiki/01-Projects/LifeOS/index.md`
- Modify: `docs/architecture.md`
- Modify: `README.md`
- Modify: `docs/operations.md`

Do not mark the old “Phase complete” claims as current until the target UI, source-link, reconciliation, and live verification gates pass. Record measured evidence, known production/local dataset differences, rollback image, backup paths, and any remaining warnings.

## 8. Acceptance criteria

The reorganization is complete only when all are true:

- Projects appear in exactly one primary LifeOS workflow.
- Areas appear in exactly one primary LifeOS workflow.
- There is no primary `Wiki` or `Context` product section.
- Task, Project, Area, Goal, and Routine records are identified by canonical wiki identity and can be rebuilt from the wiki.
- No independently authoritative LifeOS-native domain record is created for an existing or new wiki record.
- Every displayed source link is validated and resolves, or displays an explicit actionable diagnostic.
- Local and production wiki datasets are reported separately; no count is presented as universal when the mounts differ.
- Stale source hashes produce conflicts rather than silent overwrites.
- Projection reconciliation reports zero unexplained missing, orphaned, duplicate, stale, or invalid-link records.
- Authenticated browser/API smoke proves portal mutation → exact canonical Markdown → projection read-back for Project, Area, Task, Goal, and Routine workflows.
- Backup, restore, migration, and live read-back evidence is recorded.
- Deployment is pinned to a verified release image and remains healthy after restart.

## 9. Explicitly out of scope

- Replacing SilverBullet or the existing wiki.
- Flattening PARA or renaming specialist Areas for convenience.
- Copying all wiki prose into SQLite.
- Adding embeddings or a broad search platform before exact link/source correctness works.
- Creating a new generic “Context” product area.
- Declaring success from deployment health alone.

## 10. Definition of usable

Brian can open LifeOS and immediately understand:

1. what needs doing today;
2. which Projects and Areas exist;
3. where each record canonically lives;
4. what is active, paused, completed, stale, or broken;
5. how to open the real source note;
6. that every domain action changes canonical wiki state and LifeOS then reflects it;
7. whether the system is synchronized and trustworthy.

Anything less is another layer of administrative theatre, not a usable LifeOS.
