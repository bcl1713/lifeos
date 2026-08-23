# PARA-first task workflow

LifeOS presents active work through a single canonical task workflow. Every active
Task has one explicit owner path: **Project**, **Area**, or **Inbox**. The durable
record is canonical Markdown in `/wiki` (the deployed mount of
`/home/brian/wiki`); LifeOS is the authenticated source-first interface and its
SQLite data is a rebuildable projection, not a competing task store.

This document describes behavior delivered in implementation PR
[#46](https://github.com/bcl1713/lifeos/pull/46). It does not authorize a wiki
migration, a real-wiki promotion apply, a production change, or a default-profile
write.

## Choose the owner before creating a direct task

Use the **Today** page's **Add direct task** form for an intentional task creation.
The form groups the choice under **Task owner**:

- **Inbox** is only for untriaged work and requires the `Inbox` task list. It has no
  owner ID and writes beneath `00-Inbox/tasks/`.
- **Project** requires the canonical Project selected in the owner control. The
  owner ID must resolve to a canonical Project, and the task is written below that
  Project's `tasks/` directory.
- **Area** requires the canonical Area selected in the owner control. The owner ID
  must resolve to a canonical Area, and the task is written below that Area's
  `tasks/` directory.

LifeOS rejects an invalid combination rather than inferring an owner: a non-Inbox
Task without a Project or Area owner, an Inbox task paired with another list or an
owner ID, or an owner ID whose canonical type differs from the selected type fails
validation. The chosen ownership fields and task-list name are serialized in the
canonical Task Markdown.

A direct creation writes canonical Markdown first. Only after that source write
succeeds does LifeOS update the SQLite projection. If the projection cannot finish,
treat the result as reconciliation required; do not assume a database rollback
removed the canonical source.

## Use the task source as authority

Today and **Tasks** show each task's owner and source path. When that projected
path resolves to an available, safe canonical Markdown file, the view also offers
**Open canonical task source**. The link opens the authenticated LifeOS source view
for the current canonical Task file.

The path is evidence of the durable record, not a second copy in the portal. If a
projected path is absent, invalid, unsafe, or unavailable, LifeOS leaves the source
as plain text and does not emit a link. The task view remains renderable; operators
must not repair the issue by treating the projection as authority. Inspect and
correct the canonical source through the approved reconciliation process, then run
`sync_wiki_projection.py --check` before a writable rebuild. See
[`operations.md`](operations.md#projection-reconciliation).

Normal task updates preserve the existing canonical path. Changing `owner_type` or
`owner_wiki_id` is not an ordinary edit: LifeOS returns HTTP `409` and requires the
separate dry-run-first controlled-relocation workflow. See
[`task-relocation-operations.md`](task-relocation-operations.md).

## Keep daily capture separate from direct tasks

A daily-note capture is not a task. `scripts/scan_daily_captures.py` reads only
explicit capture markers and returns deterministic proposals and exceptions. It
never creates a Task, edits canonical Markdown, updates the projection, schedules
work, or changes a default-profile cron job.

The operational sequence is deliberately distinct:

1. Scan the permitted daily-note range and inspect the deterministic proposal.
2. A human accepts or rejects the proposal.
3. For the controlled-promotion candidate, bind the unmodified reviewed scanner
   proposal to a durable approval record and use only the documented fixture-only
   workflow.
4. A direct task is instead created through the Today/API source-first path with an
   explicit Project, Area, or Inbox owner.

Do not present a daily note as a mutable task list, and do not imply that scanning
or approval alone creates a task. The full scan grammar is in
[`daily-capture-scan.md`](daily-capture-scan.md); the fixture-only promotion guard
is in [`controlled-capture-promotion.md`](controlled-capture-promotion.md).

## Navigation and accessibility

The authenticated primary navigation keeps **Today**, **Projects**, **Areas**,
**Tasks**, **Data**, and **Log out** available. On narrow screens, the labelled Menu
disclosure controls that same navigation: it supports pointer input, Enter/Space,
Escape-to-close with focus return, a visible focus state, and a no-JavaScript
fallback that leaves destinations available as ordinary HTML controls. The direct
owner controls and canonical-source links are normal semantic HTML and do not
require JavaScript.

Start task work at **Today** when creating or completing an immediate task, use
**Tasks** when reviewing all projected tasks, and follow **Open canonical task
source** only to inspect the authoritative Markdown. Projects and Areas remain the
places to understand ownership context; they are not interchangeable with a task's
source file.

## Bounded default-profile operational-alignment prompt

The following is a draft prompt for a default-profile operator. It is intentionally
read-only and bounded; it does not direct any cron, skill, profile, wiki, database,
or deployment change.

```text
Perform a read-only operational-alignment review of the current LifeOS PARA-first
task workflow. Verify that direct task creation requires an explicit Project, Area,
or Inbox owner path; that canonical Markdown is the authority and SQLite is only a
rebuildable projection; and that daily-capture scan/proposal/approval remains
separate from direct task creation. Check user navigation wording for Today, Tasks,
and canonical task-source links, including the mobile/no-JavaScript navigation
fallback where available.

Do not create, edit, promote, complete, relocate, or delete any task or wiki file.
Do not run an apply, writable sync, migration, deployment, or production change.
Do not modify default-profile cron jobs, skills, configuration, credentials, or
memory. Return a concise findings-only report with: observed evidence, mismatches,
and any proposed follow-up that requires an explicit human approval.
```

Use the prompt as a review request only. Any follow-up that would mutate a default
profile, canonical source, projection, or deployment remains a separately scoped and
explicitly approved task.
