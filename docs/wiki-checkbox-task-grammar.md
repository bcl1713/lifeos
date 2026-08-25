# Wiki checkbox task grammar and discovery contract

Status: executable specification for Issues #57 and #71. This contract intentionally
defines input, outputs, identities, and diagnostics before scanner implementation.

## Scope and purity

A future scanner is a read-only function of a configured wiki root and this policy.
It has **no filesystem source writes**, **no DB dependency**, and **no task/projection mutation**. It must not create directories, update linked task records, reconcile
SQLite, or alter checkbox text. Canonical Markdown is never rewritten to make it
parse.

The scanner returns immutable task snapshots and diagnostics. It is not a task
mutation API, watcher, UI adapter, cache builder, or migration tool.

## Scan policy

The default allowed roots are `01-Projects`, `02-Areas`, and `dailies`. A scanner
considers only regular UTF-8 `.md` files below those roots, recursively. It must walk
root-relative POSIX paths in lexical order and process valid or malformed checklist
lines in increasing one-based line order. Thus observations are ordered by **path, then line**.
Diagnostics are ordered by path, line, checkbox-level finding before
per-link findings, `link_index`, then stable code rank; repeated equal findings retain
discovery order.

The default exclusions are `03-Research`, `04-Archives`, `assets`, `templates`, hidden
paths, and any path outside the allowed roots. In addition, a deployment policy may
add exclusions for generated directories; it must report the effective policy rather
than silently inventing exclusions. `lifeos/tasks` is not categorically excluded: a
typed record there is a valid optional metadata target, but a checkbox inside one is
only discovered if its containing path is otherwise allowed.

The fixtures in `tests/fixtures/wiki_checkbox_tasks/expected.json` are the executable
baseline. Their `excluded_paths` contain checkbox text that must not yield tasks or
diagnostics under the default policy.

## Supported checkbox grammar

A supported task is exactly one Markdown unordered-list item:

```text
<indent>- [ ] <label>
<indent>- [x] <label>
```

`<indent>` is zero or more spaces; nested lists are therefore supported. There is one
ASCII space after `-`, exactly one space or lowercase/uppercase `x` between `[` and
`]`, and one ASCII space before a non-empty `<label>`. `x` is case-insensitive, so
`- [X] Review daily capture` is checked. `[ ]` is unchecked. The scanner preserves the
label after removing the checkbox prefix; it does not normalize Markdown prose,
indentation, or link display text.

Everything checkbox-like that begins as a list item but is not this grammar (for
example `- [y] Unsupported checkbox state`, a missing label, or extra state
characters) is not a task and produces `MALFORMED_CHECKBOX`. Checkbox-looking prose
outside an unordered-list item is ordinary prose and has no diagnostic. Ordered lists,
`*`/`+` bullets, task extensions, HTML checkboxes, and nested non-list syntax are
unsupported in this phase.

## Supporting links and explicit typed task links

Every ordinary Markdown link and canonical wiki link in checkbox prose is
supporting/amplification context, never a typed task record. For example:

```markdown
- [ ] Populate the roster ([source details](trips/26-15.md#key-personnel))
```

The checkbox label is preserved exactly. Supporting links preserve their authored
display text, destination, and mixed Markdown/wiki source order. Safe Markdown targets
resolve relative to the containing checklist file; a safe query and fragment are
retained on its navigation action. `http(s)` Markdown destinations are literal
no-fetch external actions. Missing, unsafe, and non-Markdown Markdown destinations
emit respectively `SUPPORTING_LINK_MISSING`, `SUPPORTING_LINK_UNSAFE`, and
`SUPPORTING_LINK_NON_MARKDOWN`.

Canonical wiki supporting links use exactly `[[target]]`, `[[target|display text]]`,
`[[target#anchor]]`, or `[[target#anchor|display text]]`. They are resolved using the
rendered-source convention: root-relative candidate, source-relative candidate, then
a unique bare-name match. Extensionless targets are Markdown candidates. They never
load typed metadata. Invalid, unsafe, missing, and ambiguous wiki targets emit
`SUPPORTING_WIKI_LINK_MALFORMED`, `SUPPORTING_WIKI_LINK_UNSAFE`,
`SUPPORTING_WIKI_LINK_MISSING`, or `SUPPORTING_WIKI_LINK_AMBIGUOUS` respectively.

Only an inline Markdown link destination with the exact lowercase raw `task:` prefix
opts into optional typed metadata:

```markdown
- [ ] [Change brakes](task:lifeos/tasks/change-brakes.md)
```

The marker is scanner syntax, not an action URL. It is recognized before percent
decoding; its payload is decoded exactly once and must be a non-empty relative `.md`
path. Malformed percent escapes, literal or escaped spaces (use `%20`), absolute or
scheme/netloc paths, traversal, fragments, and queries are malformed. A label may
contain zero or one marker. Two or more markers emit
`TYPED_TASK_LINK_CARDINALITY` and none is selected; a malformed marker emits
`MALFORMED_TYPED_TASK_LINK` and is not reclassified as supporting. The checkbox
occurrence remains the task observation; optional typed metadata never changes its
state.

Link handling is deliberately narrow:

1. Use typed metadata only when exactly one explicit `task:` destination satisfies this
   grammar. Fragments and query strings are unsupported for typed-task links.
2. Resolve the path component relative to the containing checklist file. It must be a
   relative, root-contained `.md` regular file. Absolute paths, URI schemes, query
   strings, and resolution that escapes the configured wiki root are unsafe. A fragment
   is permitted only for an ordinary supporting link and is never used while reading it.
3. Preserve existing source-safe navigation: use root containment before reading and do
   not follow an escaping symlink. The implementation must not weaken existing
   root-escape, symlink, or permission protections.
4. Parse its frontmatter as a canonical typed record and require `type: task` plus a
   non-empty `id`. A missing target gives `MISSING_TASK_RECORD`; a readable target
   without a usable typed task record gives `UNTYPED_TASK_RECORD`; a typed non-task
   record gives `WRONG_TASK_RECORD_TYPE`; an unsafe destination gives
   `UNSAFE_TASK_LINK`.

An exactly-one unmarked Markdown link that safely resolves to a typed-shaped record is
supporting-only and emits non-fatal `LEGACY_TYPED_TASK_LINK`; it must not load metadata,
compare state, or emit ordinary typed-record diagnostics. Wiki links never receive the
legacy diagnostic merely for resembling a task. A failure to use any link as metadata
does not suppress the valid checkbox occurrence.

## State, identity, and repeated references

Checkbox state is authoritative: `[ ]` is open and `[x]` is completed. A linked task
record status is metadata-only during this transition. If an open checkbox links to a
record with `status: completed`, or a completed checkbox links to a record with
`status: open`, emit `CHECKBOX_STATUS_DISAGREEMENT` at the checkbox locator. It is a
warning with the message `Checkbox is <checkbox state> but linked task record status
is <record status>; checkbox state remains authoritative.` and includes the safe
`link_destination` and `linked_record_path`. Other linked-record statuses are
metadata without a checkbox-state equivalence in this phase and do not produce this
diagnostic. The scanner never writes either source.

Identity has two layers:

- A **checkbox occurrence** is identified by its source locator. For a valid linked
  record, its display identity is `linked_task_id + occurrence locator`, not the
  record ID alone. The linked task record is metadata identity, never the checkbox
  occurrence identity.
- An initial plain checkbox has no durable mutable task identity. It is displayed
  read-only with `source_path + normalized occurrence-context content fingerprint`.
  The fingerprint deliberately includes more than a line number, but edits that
  change its context, moves and renames can change it. The snapshot must say that
  limitation; it must not imply that a plain checkbox can safely drive a mutation.

One linked task record may be referenced by multiple checkbox occurrences. Keep every
occurrence, in deterministic order, because each checkbox owns its own visible state.
Emit `DUPLICATE_LINKED_TASK_RECORD` for every occurrence in a repeated-reference set,
including the first. Do not silently deduplicate, merge status, or choose a winner.

Moves and renames change the source locator path. Linked metadata record IDs survive a
record move but do not make the occurrence locator stable; the new location is a new
observation until a later explicitly approved continuity policy says otherwise.

## Source location and diagnostics schema

Every task and diagnostic uses a one-based source locator:

```json
{
  "source_path": "01-Projects/Alpha/index.md",
  "line": 4,
  "column": 3,
  "source_excerpt": "  - [x] [Change brakes](lifeos/tasks/change-brakes.md)"
}
```

`source_path` is a root-relative POSIX path. `line` is the physical source line.
`column` is the one-based column of the list marker `-`; it preserves nested-list
location without claiming it is a durable identity. `source_excerpt` is the complete
physical line, capped by a documented future implementation limit only if that limit
is also reported. A linked record, when valid, carries a separate safe
`linked_record_path`; its location must never replace the checkbox source locator.

Diagnostics are immutable objects with `code`, `severity` (`warning` for all current
input findings), `message`, and the source locator. Per-link diagnostics additionally
include their zero-based mixed-source-order `link_index`, `link_kind`, and a literal
`link_destination` only when safe to disclose. They may include safe
`linked_record_path` values. They must never put host-absolute paths, file contents
other than the excerpt, or database identifiers in the result. The complete link codes
are `TYPED_TASK_LINK_CARDINALITY`, `MALFORMED_TYPED_TASK_LINK`,
`LEGACY_TYPED_TASK_LINK`, `SUPPORTING_LINK_UNSAFE`, `SUPPORTING_LINK_MISSING`,
`SUPPORTING_LINK_NON_MARKDOWN`, `SUPPORTING_WIKI_LINK_MALFORMED`,
`SUPPORTING_WIKI_LINK_UNSAFE`, `SUPPORTING_WIKI_LINK_MISSING`,
`SUPPORTING_WIKI_LINK_AMBIGUOUS`, `UNSAFE_TASK_LINK`, `MISSING_TASK_RECORD`,
`UNTYPED_TASK_RECORD`, `WRONG_TASK_RECORD_TYPE`, `DUPLICATE_LINKED_TASK_RECORD`,
and `CHECKBOX_STATUS_DISAGREEMENT`.

## Compatibility boundary

Current explicit owner/task-directory placement remains intact. The existing
`01-Projects/<owner>/lifeos/tasks/` typed task records remain legacy typed task records
and optional metadata only; this specification neither relocates them nor creates new
ones. Their existing API/projection lifecycle is not reinterpreted here.

`dailies` remains supported for daily capture. Plain daily checkboxes are visible with
the same read-only source-path/fingerprint limitation; there is no automatic promotion
into a typed task record. Checkboxes in Project and Area notes are equally source
observations, not a new owner-placement rule.

This phase makes no compatibility promise that old SQL-backed task lists and checkbox
occurrences are one combined list. A later read-model/cutover phase must prevent double
rendering explicitly, keep legacy typed task records readable, and preserve
source-safe navigation. No scanner result licenses DB retirement, task-directory
migration, real-wiki application, or source mutation.
