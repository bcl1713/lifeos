# Wiki checkbox task discovery: operator and user guide

Status: the checkbox read and refresh contract in [PR #65](https://github.com/bcl1713/lifeos/pull/65)
and [PR #66](https://github.com/bcl1713/lifeos/pull/66) is integrated to `dev`.
The no-projection-DB read compatibility and scanner CLI additions are independently
reviewed in [PR #69](https://github.com/bcl1713/lifeos/pull/69) at
`a100b0c9286ed1a2454e065c5bb5218da626d146`. Their use requires that PR and this
documentation change to be independently reviewed and merged to `dev`; neither is
evidence of a production deployment or a `main` action.

The grammar, identity, and diagnostic rules remain the executable contract in
[wiki-checkbox-task-grammar.md](wiki-checkbox-task-grammar.md). This guide
explains how the browser, API, refresh loop, and recovery behavior use that
contract.

## What users see

After authentication, **Today** (`/`) shows only open (`- [ ]`) checkbox
observations. **Tasks** (`/tasks`) shows both open and checked (`- [x]` or
`- [X]`) observations. Both order observations deterministically by canonical
source path and then source line.

A checkbox occurrence is an observation, not an editable LifeOS Task. The
browser renders disabled checkboxes and does not show create, complete, reopen,
pause, archive, or other checkbox-mutation controls. To change state, edit the
approved canonical Markdown checklist source directly. The scanner, refresh
coordinator, browser routes, and checkbox API never write source Markdown,
create a task record, update a linked record, or fall back to SQLite/SQL task
rows. SQLite remains outside this read model's authority boundary.

Each rendered observation includes its root-relative source path, line, and
column. When safe navigation is available, **Open checklist source** opens the
current canonical source. A checkbox can optionally link to a typed task record;
its title, Summary, and priority are metadata only. **Open linked task record**
is shown only when that target resolves safely. Unsafe, missing, untyped, or
wrong-type targets remain non-clickable and appear as scanner diagnostics; they
do not hide a valid checkbox occurrence.

### Checkbox links: context versus typed metadata

Ordinary Markdown links and canonical wiki links in a checkbox label are
supporting context. LifeOS preserves the checkbox label and exposes each safe
supporting link separately in authored mixed-link source order. A safe relative
Markdown target may retain its query and fragment for its navigation action;
an `http` or `https` target is a literal external action. LifeOS does not fetch
external destinations. Canonical wiki forms are `[[target]]`,
`[[target|display]]`, `[[target#anchor]]`, and
`[[target#anchor|display]]`; their resolution follows rendered-source
navigation (root-relative, source-relative, then a unique bare-name match).
Supporting links never load typed task metadata.

Only an inline Markdown destination with the exact lowercase raw prefix
`task:` opts into typed metadata, for example
`[Change brakes](task:lifeos/tasks/change-brakes.md)`. The scanner recognizes
the marker before decoding its payload, decodes that payload exactly once, and
requires a non-empty relative Markdown path. Encode a path space as `%20`; it
then becomes a path space after that one decode. A raw literal space, malformed
percent escape, traversal, absolute or
scheme/netloc paths, queries, and fragments are malformed. A checkbox may have
zero or one such marker. Multiple markers emit `TYPED_TASK_LINK_CARDINALITY`;
a malformed marker emits `MALFORMED_TYPED_TASK_LINK`; neither selects metadata.

An unmarked Markdown link that safely resolves to a typed-shaped task record is
still supporting context. It produces the non-fatal `LEGACY_TYPED_TASK_LINK`
diagnostic and does not load the record, compare status, or turn the checkbox
into a typed task. Invalid, unsafe, missing, ambiguous, and non-Markdown
supporting targets similarly remain visible context with their applicable
diagnostic. No link diagnostic removes the checkbox observation or causes an
automatic repair.

The source-navigation safety contract is the same one used elsewhere in LifeOS:
links must remain under the configured wiki root and cannot traverse an escaping
symlink. With no `LIFEOS_SILVERBULLET_BASE_URL`, links remain on LifeOS's
authenticated `/sources/wiki/...` route. That optional setting can point valid
canonical links at the mounted SilverBullet wiki instead; see
[rendered-source-navigation.md](rendered-source-navigation.md). It does not
make LifeOS operate or health-check SilverBullet.

## Discovery scope and diagnostics

The canonical Markdown scanner is the authoritative read source. It scans only
regular UTF-8 Markdown files under `01-Projects`, `02-Areas`, and `dailies`.
It excludes `03-Research`, `04-Archives`, `assets`, `templates`, hidden paths,
paths outside those roots, and any extra comma-separated exclusions configured
by the deployment. It reports the effective roots and exclusions in the API
response.

The scanner preserves every valid occurrence, including repeated links to the
same typed task record. Checkbox state remains authoritative over a linked
record's status. Input findings are displayed in the browser and returned in
`diagnostics`; examples include malformed checkbox grammar, unsafe or missing
links, unusable linked records, repeated linked records, and checkbox/linked
record status disagreement. Correct the canonical Markdown source or its linked
record deliberately; diagnostics do not trigger automatic repair.

When more than one checkbox occurrence links to the same typed task record, the
scanner emits `DUPLICATE_LINKED_TASK_RECORD` for every occurrence in that set,
including the first. Each occurrence remains visible at its own source locator:
do not merge, deduplicate, select a winner, or render it twice through a typed
task list.

## No-projection-DB read compatibility and scanner CLI

The checkbox read model is scanner-authoritative. Removing a projection SQLite
database and initializing a replacement does not change canonical checkbox reads:
the scanner reads the configured canonical Markdown, not the projection database.
The checkbox endpoint does not merge checkbox observations with legacy typed task
records or fall back to SQL rows.

Legacy typed task records linked from a checkbox remain optional readable metadata
(title, Summary, and priority). They neither control checkbox state nor replace a
checkbox occurrence. A plain checkbox remains a read-only observation and is not
promoted into a typed task record.

Use the scanner-only command to inspect a configured wiki root:

```bash
python scripts/scan_wiki_checkbox_tasks.py --wiki-root /wiki
```

It prints deterministic JSON with `tasks`, `diagnostics`, and the effective
`policy`. Repeat `--exclude DIRECTORY` to add each directory name to the scanner
exclusions, for example:

```bash
python scripts/scan_wiki_checkbox_tasks.py \
  --wiki-root /wiki \
  --exclude generated \
  --exclude vendor
```

This command is read-only: it does not write canonical Markdown, use the
projection SQLite database, create a migration, or change checkbox state. Use it
for inspection only; update approved checklist Markdown directly when a checkbox
state or source diagnostic requires correction.

## API and inspection

`GET /api/v1/checkbox-tasks` is authenticated and returns JSON with `tasks`,
`diagnostics`, and the effective scan `policy`. It accepts `state=all` (the
default), `state=open`, or `state=checked`. The response is constructed from a
fresh canonical scanner result, never a SQL fallback. Each task's additive
`supporting_links` list preserves link source order and provides its kind,
zero-based `link_index`, authored destination/display information, safe
resolved path/navigation action when available, classification, and diagnostic.
Per-link diagnostics likewise identify `link_index` and `link_kind`; existing
task, source, linked-record, and policy fields remain additive/compatible.
A successful scan of a configured but empty wiki is normal: the browser routes
return HTTP `200` with the appropriate empty state and the API returns HTTP
`200` with `tasks: []`.

Use this read-only inspection sequence after the merged build is deployed to a
non-production test environment or during an approved operational verification:

1. Sign in and confirm Today contains only open checklist observations.
2. Open Tasks and confirm checked observations are included, source locations are
   correct, and no mutation controls are present.
3. Follow only an available source or linked-record action and confirm it stays
   within the canonical wiki navigation boundary.
4. Request `/api/v1/checkbox-tasks?state=open` and confirm the JSON filtering
   matches Today. Check `policy` and `diagnostics` before changing source files.
5. For an empty configured fixture/wiki, confirm `200` and an empty result rather
   than treating it as an outage.

Do not use this guide to run a real-wiki apply. There is no checkbox apply
command, migration, or source-write operation in this feature.

## Refresh, watcher, and restart behavior

When the scheduler lifespan is enabled and a canonical wiki is configured, the
refresh coordinator scans immediately at startup and then periodically. The
normal interval is `LIFEOS_CHECKBOX_REFRESH_INTERVAL_SECONDS`, defaulting to the
scheduler interval (normally 900 seconds). Requested scans are debounced by
`LIFEOS_CHECKBOX_REFRESH_DEBOUNCE_SECONDS`, default `1` second. The latest
snapshot is in memory only; a refresh does not create a cache, projection row,
or write source.

An optional watchdog observer can accelerate the next scan:

- Set `LIFEOS_CHECKBOX_WATCHER_ENABLED=1` to request watcher acceleration.
  It is disabled by default.
- The image installs the optional `watchdog` dependency. If it cannot be
  imported, or the observer cannot start because of an `OSError`, LifeOS records
  the watcher diagnostic as `unavailable: ImportError` or `unavailable: OSError`
  and continues periodic scanning. A disabled watcher reports `disabled`; a
  started watcher reports `active`.
- Watcher events, including overflow or bursts, only request the same debounced
  scanner pass. They neither parse independently nor mutate data.
- Periodic scanning is the recovery path for missed watcher events. On restart,
  the coordinator immediately scans the current canonical wiki again, so a
  prior in-memory snapshot is not reused as authority.

For troubleshooting, first check the configured wiki mount and the application
logs for the watcher diagnostic. Do not compensate for an unavailable watcher by
writing SQL, editing a projection, or enabling a source-writing job; periodic
scanner reconciliation remains authoritative.

## Browser and API recovery

A missing wiki configuration and a configured-but-unavailable wiki are outages,
not empty scans:

| Condition | Today / Tasks | Checkbox API |
| --- | --- | --- |
| Wiki is not configured | Authenticated HTML `503` page saying the canonical repository has not been configured; configure it and refresh. | JSON `503`: `{"detail":"Canonical wiki repository is not configured"}` |
| Configured wiki is unavailable (including an invalid root) | Authenticated HTML `503` page saying LifeOS cannot reach the configured repository; check availability and refresh. | JSON `503`: `{"detail":"Canonical wiki repository is unavailable"}` |
| Configured wiki scans successfully with no observations | Normal HTML `200` empty state. | JSON `200` with an empty `tasks` array. |

The browser recovery page preserves the authenticated LifeOS navigation and
session context. It intentionally uses human guidance rather than exposing the
API detail string. Automation must keep using `/api/v1/checkbox-tasks` and
handle its JSON `503` semantics; it must not scrape the browser recovery HTML.

## Boundaries and rollout

This documentation authorizes no source writes, real-wiki apply, schema or data
deletion, deployment, release, production change, or `main` action. It does not
alter the existing source-first `/api/tasks` lifecycle for canonical typed Tasks,
the daily-capture review workflow, or projection reconciliation. Independent
documentation review and a separate merge/verification phase remain required
before relying on the PR #69 additions in an integration or operational
environment.
