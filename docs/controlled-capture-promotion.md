# Controlled capture promotion operator contract

This contract describes the reviewed, fixture-only controlled-promotion candidate in
[PR #38](https://github.com/bcl1713/lifeos/pull/38). It becomes available only after
that implementation is merged into `dev` and included in the image being exercised.
It is not authorization to apply against a real wiki, production, `/home/brian/wiki`,
`/wiki`, or any default-profile asset. A real-wiki promotion remains a separate Brian
named-target, reviewed-proposal/mapping, backup, and maintenance-window gate.

## Scope and invariants

`scripts/scan_daily_captures.py` remains a read-only proposal generator. Promotion
accepts one **unmodified reviewed scanner proposal** plus one durable approval record,
then only when `--apply` is explicit. It does not translate a proposal into an ad hoc
`task` or `{owner_id, task_list}` payload.

The scanner proposal is the identity-bearing input:

| Field | Required contract |
| --- | --- |
| `capture_id` | Immutable capture identity. |
| `source_path` | Root-relative Markdown daily-note path. |
| `source_line` | One-based source line containing the capture. |
| `source_hash` | SHA-256 of that exact UTF-8 capture line, not of the whole file. |
| `title` | Title for the canonical task. |
| `target` | Exact `{ "type", "id", "path" }` target identity from the scan. Inbox is `{ "type": "inbox", "id": null, "path": "00-Inbox" }`; project and area targets retain their stable ID and canonical path. |
| `due` | Optional ISO date or `null`; `null` creates a task with no due date. |
| `priority` | Explicit integer `0`–`3` or `null`; omitted scanner priority (`null`) deterministically becomes canonical priority `0`. |

Before any canonical write, promotion verifies the exact-line hash, source path and
line, the current canonical target identity, task-list availability, and that the
capture-derived task identity is unclaimed. A stale line/hash, changed or invalid
target, duplicate task identity, missing approval, or approval/payload mismatch fails
before writes.

## Durable approval binding

The approval JSON is a durable review record. It must contain all of:

- a non-empty durable `approval_id`;
- `approved_proposal`, canonically identical to the complete reviewed scanner
  proposal; and
- `proposal_fingerprint`, the SHA-256 of canonical JSON for that same complete
  proposal (sorted keys, compact separators, UTF-8).

The approval binds the entire payload, including the capture identity, exact line hash,
title, optional due/priority values, and `{type, id, path}` target. A new title,
target, source hash, or any other proposal alteration requires a newly reviewed,
matching approval; do not reuse or hand-edit an old approval.

## Fixture-only apply workflow

Use only a disposable fixture root created for this test. The root must contain a
regular, non-symlink `.lifeos-fixture` file whose entire content is exactly:

```text
lifeos-test-fixture-v1
```

The CLI resolves the requested root and refuses all of the following before it reads
or writes proposal data:

- either protected root: `/wiki` or `/home/brian/wiki`;
- a root without `.lifeos-fixture`;
- a symlinked marker;
- a marker that is not a regular file; or
- a marker whose content differs from the exact value above.

The canonical source path must also remain a Markdown path beneath the chosen fixture
root; absolute paths, traversal, symlink traversal, and missing source files are
rejected. These are fail-closed test-fixture checks, not a way to bless another wiki.
No real-wiki/default-profile use is authorized.

After preparing a fixture database, the reviewed proposal JSON, and the matching
approval JSON, perform the dry run first:

```bash
uv run python scripts/promote_capture.py \
  --database sqlite:///./fixture-lifeos.db \
  --fixture-root /absolute/path/to/lifeos-test-fixture \
  --proposal-file /absolute/path/to/reviewed-proposal.json \
  --approval-file /absolute/path/to/durable-approval.json
```

A dry run prints `{"status":"dry_run","capture_id":"..."}` and performs no
canonical write. Only the same command with `--apply` may create the canonical task
source and daily-note receipt. Do not substitute `/wiki`, `/home/brian/wiki`, a
profile directory, or a default-profile artifact for the fixture paths shown above.

## Apply result, provenance, and recovery

On a successful apply, exactly one owner-local canonical Task is created using the
reviewed target: Inbox uses its canonical Inbox placement; Project and Area targets
resolve to their current canonical owner and use that owner's task placement. The task
records durable capture provenance including `capture_id`, `source_path`,
`source_hash`, exact `target`, `approval_id`, and `proposal_fingerprint`.

The original daily capture receives one idempotent receipt backlink:

```text
<!-- lifeos-capture-receipt
capture-receipt: CAPTURE_ID
task-wiki-id: tsk-capture-CAPTURE_ID
proposal-fingerprint: SHA256
-->
```

A repeat apply with the same proposal/approval is an idempotent no-op and returns
`status: "unchanged"` only when that same capture-derived task and matching receipt
already exist. An existing task identity without the matching receipt is an error, not
permission to append one.

The operation is source-first. If the canonical Task source is written but the task
projection cannot complete, or if the daily receipt cannot complete after that source
write, the operation reports reconciliation required. It never claims rollback and
must not be retried blindly. Preserve the proposal and approval, inspect the canonical
Task and daily source in the fixture, run the normal non-mutating reconciliation check,
and reconcile the proven source state before any further fixture test.

## Deterministic review records

The reviewed candidate renders canonical Markdown review records from scan and
projection/reconciliation evidence. Records are idempotent per cadence and period:

- weekly: `01-Projects/LifeOS/lifeos/reviews/weekly-YYYY-Www.md`;
- monthly: `01-Projects/LifeOS/lifeos/reviews/monthly-YYYY-MM.md`.

Each record has `type: review_record`, stable cadence/period identity, and a
`source_backlinks` evidence payload. The payload deterministically includes these
categories: `unpromoted_captures`, `inbox_items`, `overdue_or_due_next`,
`stalled_or_no_next_action_owners`, and `reconciliation_exceptions`. Capture entries
retain their daily-note source path; canonical task and owner entries retain wiki ID,
source path, and title; recognized reconciliation exceptions receive the same source
backlinks when their records are available. Re-rendering the same period with the same
source state overwrites the same canonical review path rather than creating another
record.

This fixture-only documentation deliberately creates no cron handoff, no real-wiki
review record, and no default-profile action. Those remain separate, explicitly gated
future work.
