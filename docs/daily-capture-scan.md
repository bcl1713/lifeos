# Daily-capture scan contract

The daily-capture scanner is a **review-only reader** for explicitly marked lines in
canonical Markdown daily notes. Its implementation is delivered by [PR #35](https://github.com/bcl1713/lifeos/pull/35).

The scan produces deterministic JSON proposals for a human to route and promote
through the normal canonical task workflow. It is not a task-creation command.

## Run a scan

Run the repository script with a canonical wiki root, a daily-note directory relative
to that root, and an inclusive ISO-date range:

```bash
uv run python scripts/scan_daily_captures.py \
  --wiki-root /wiki \
  --daily-root Daily \
  --from 2026-08-23 \
  --to 2026-08-23
```

Options:

- `--wiki-root` defaults to `/wiki`.
- `--daily-root` is required. It must be a non-symlink directory path relative to
  `--wiki-root`; it cannot be absolute, `.`/empty, contain `..`, or escape the
  canonical root.
- `--from` and `--to` are required, inclusive `YYYY-MM-DD` dates. `--to` cannot
  precede `--from`.

Only regular `*.md` files beneath `--daily-root` whose **filename stem** is an ISO
calendar date inside the requested range are read. Symlinked files and files with
non-date stems are ignored. A missing valid daily directory produces an empty report.

## Exact opt-in grammar

Only one complete, unindented line in this form is a candidate:

```text
- [ ] [lifeos-capture id=IMMUTABLE_ID target=inbox|project:STABLE_ID|area:STABLE_ID due=YYYY-MM-DD priority=0..3] TITLE
```

`id` and `target` are required; `due` and `priority` are optional. Attributes are
space-separated `key=value` pairs. The only recognized keys are `id`, `target`,
`due`, and `priority`; duplicate, missing, unknown, or malformed attributes are
invalid. Valid attributes may appear in any order. The title must be nonempty and
may not begin or end with whitespace.

- `IMMUTABLE_ID` and a target `STABLE_ID` start with a letter and then use 2–127
  letters, digits, `_`, or `-` characters.
- `target=inbox` resolves to canonical path `00-Inbox`.
- `target=project:STABLE_ID` or `target=area:STABLE_ID` must resolve to an active
  canonical Project or Area with that exact stable ID. A missing, wrong-type, or
  inactive target is not proposed.
- `due`, when present, must be a real canonical `YYYY-MM-DD` date.
- `priority`, when present, is exactly one of `0`, `1`, `2`, or `3`.

Ordinary unchecked checklist items and lines without the exact `lifeos-capture`
marker are ignored. Do not reformat canonical Markdown merely to make a line render
or scan differently: the line itself is the intentional source input.

## Deterministic report

The command prints one JSON object, with keys sorted by the CLI, containing:

```text
{
  "proposals": [...],
  "exceptions": [...]
}
```

A proposal has these fields:

| Field | Meaning |
| --- | --- |
| `capture_id` | The explicit immutable capture ID. |
| `source_path` | Canonical-root-relative Markdown path. |
| `source_line` | One-based line number. |
| `source_hash` | SHA-256 of the exact UTF-8 capture line. |
| `title` | The captured title text. |
| `target` | `{ "type", "id", "path" }`; Inbox has `type: "inbox"`, `id: null`, and `path: "00-Inbox"`. |
| `due` | Date string or `null`. |
| `priority` | Integer `0`–`3` or `null`. |

Every exception has `capture_id` (or `null`), `source_path`, `source_line`, `code`,
and `detail`. Exception codes are:

- `malformed_capture` — the marker, attributes, ID, optional date, or priority does
  not use the required grammar.
- `invalid_target` — the target spelling is not `inbox`, `project:<stable-id>`, or
  `area:<stable-id>`.
- `stale_target` — a syntactically valid target does not resolve to the declared,
  active canonical destination.
- `duplicate_capture_id` — the capture ID occurs more than once in the requested
  window. Every occurrence is reported and none is proposed.
- `already_promoted` — exactly one canonical Task already carries this capture ID
  and the same source hash.
- `source_changed` — exactly one canonical Task already carries this capture ID but
  its stored source hash differs.
- `canonical_authority_conflict` — canonical record identity is ambiguous; scanning
  stops without proposals until the canonical conflict is resolved.
- `duplicate_promoted_capture_id` — more than one canonical Task carries the same
  capture ID; scanning stops without proposals until it is resolved.

Proposals sort by `source_path`, `source_line`, then `capture_id`. Exceptions sort by
`source_path`, `source_line`, `capture_id`, then `code`. The scan has no clock-based
or random fields, so the same canonical input yields the same report.

## Human routing and duplicate handling

A proposal is review material, not an instruction to mutate the wiki. A human decides
whether to discard it or to create a Task through the established source-first,
canonical Markdown workflow. When a proposal is promoted, preserve both
`daily_capture_id` and `daily_capture_source_hash` on that canonical Task.

On later scans, the scanner finds Task records by `daily_capture_id`:

- same ID plus same hash is `already_promoted`, preventing a duplicate proposal;
- same ID plus a changed line/hash is `source_changed`, requiring human review;
- duplicate capture IDs in daily notes or duplicate promoted IDs in canonical Tasks
  are exceptions, never a choice made implicitly by the scanner.

## Explicit non-goals and safety boundary

The scanner reads canonical records and selected daily Markdown only. It never:

- creates, promotes, changes, completes, or archives a Task;
- edits daily notes, wiki Markdown, or any other canonical record;
- writes SQLite projections, journals, or audit data;
- schedules work or configures a default-profile cron job;
- treats rendered output as canonical input or alters canonical Markdown for rendering.

Use normal LifeOS source-first mutation and projection-reconciliation procedures after
a human has approved a separate promotion action. See `docs/architecture.md` for the
canonical-authority and mutation contract, and `docs/operations.md` for operational
reconciliation guidance.
