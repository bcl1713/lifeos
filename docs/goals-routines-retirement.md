# Goals and Routines retirement contract

Issue: [#42](https://github.com/bcl1713/lifeos/issues/42)

Implementation: [PR #43](https://github.com/bcl1713/lifeos/pull/43)

## Status and boundary

Goals and Routines are retired LifeOS domains. They are no longer active workflow surfaces, and the primary navigation intentionally has no Goals or Routines links.

Authenticated API and browser workflow routes for either retired domain return HTTP `410 Gone`. The response detail includes:

```json
{
  "code": "legacy_domain_retired",
  "message": "...",
  "report_path": "/api/legacy/goals-routines/report"
}
```

New Project and Task requests must not supply legacy Goal or Routine relationships. A non-null legacy `goal_id` or `routine_id` is rejected with the same HTTP `410` retirement response.

Existing Goal and Routine projection rows remain only to support inventory and the report below. They are not an active source of workflow behavior.

## Read-only retirement report

`GET /api/legacy/goals-routines/report` is authenticated and is the only retirement inventory endpoint. It is always a dry run:

```json
{
  "mode": "dry-run",
  "writes_performed": false,
  "legacy_goals": [],
  "routine_mappings": [],
  "blocking_exceptions": [],
  "summary": {
    "legacy_goals": 0,
    "legacy_routines": 0,
    "ready_mappings": 0,
    "blocking_exceptions": 0
  }
}
```

The report returns the following fields:

- `legacy_goals`: each retained legacy row with `source` (`table`, `row_id`, `wiki_id`), proposed `action: "archive"`, `title`, and `status`.
- `routine_mappings`: each reviewable recurrence mapping with `source`, `target`, and `recurrence_metadata`.
- `blocking_exceptions`: rows that cannot be safely mapped, with `source`, `code`, and `message`.
- `summary`: counts for `legacy_goals`, `legacy_routines`, `ready_mappings`, and `blocking_exceptions`.

`recurrence_metadata` preserves `cadence`, `next_run_date`, `minimum_occurrences`, `frequency_window_days`, and ordered `skips` data. A `target` is one of:

- `{ "owner_type": "project", "owner_wiki_id": "..." }`
- `{ "owner_type": "area", "owner_wiki_id": "..." }`
- `{ "owner_type": "inbox", "owner_wiki_id": null }`

The report is deterministic and idempotent: repeating it against unchanged projection and wiki data returns the same inventory and does not write to SQLite or canonical Markdown.

## Mapping limits and review

A routine can map to a Project or Area only when its persisted occurrence tasks resolve to exactly one explicit canonical owner. The owner must still resolve to a canonical record of the declared type.

Inbox is permitted only when the routine belongs to the Inbox task list. It is not a general fallback for routines without an owner.

Missing, invalid, or multiple Project/Area owners create a `blocking_exceptions` record rather than a guessed mapping. Resolve every blocking exception and have a human review every proposed archive/mapping before any later, separately authorized migration work.

## Explicit non-behavior

This endpoint has no apply mode. It does not:

- archive or delete Goals or Routines;
- create, update, delete, or rewrite tasks, projects, areas, recurrence metadata, SQLite rows, or wiki Markdown;
- resolve ambiguity automatically; or
- schedule or generate routine task occurrences.

The scheduler is inert for retired routines. Any future migration or cleanup must be designed and authorized separately; do not infer permission to change canonical wiki content or operational data from this report.
