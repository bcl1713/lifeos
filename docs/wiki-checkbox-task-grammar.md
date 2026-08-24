# Wiki checkbox task grammar and discovery contract

Status: executable specification for Issue #57. This contract intentionally defines
input, outputs, identities, and diagnostics before scanner implementation. Issue #58
may implement it but may not broaden it implicitly.

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
lines in increasing one-based line order. Thus externally visible output is ordered by
**path, then line**, then diagnostic code when two diagnostics have the same source
location.

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

## Optional linked metadata record

A valid label may contain one ordinary relative Markdown link, for example:

```markdown
- [ ] [Change brakes](lifeos/tasks/change-brakes.md)
```

The checkbox occurrence is the task observation. The destination is optional metadata:
title/summary/priority may be read only after safe resolution, and no linked record
changes checkbox state.

Link handling is deliberately narrow:

1. Use the link destination only when there is exactly one Markdown link in the label.
   Fragments and query strings are unsupported for task-record links.
2. Resolve it relative to the containing checklist file. It must be a relative,
   root-contained `.md` regular file. Absolute paths, URI schemes, fragments, query
   strings, and resolution that escapes the configured wiki root are unsafe.
3. Preserve existing source-safe navigation: use root containment before reading and do
   not follow an escaping symlink. The implementation must not weaken existing
   root-escape, symlink, or permission protections.
4. Parse its frontmatter as a canonical typed record and require `type: task` plus a
   non-empty `id`. A missing target gives `MISSING_TASK_RECORD`; a readable target
   without a usable typed task record gives `UNTYPED_TASK_RECORD`; a typed non-task
   record gives `WRONG_TASK_RECORD_TYPE`; an unsafe destination gives
   `UNSAFE_TASK_LINK`.

A failure to use a link as metadata does not suppress the valid checkbox occurrence.
The occurrence remains visible as a plain, read-only observation with its diagnostic.

## State, identity, and repeated references

Checkbox state is authoritative: `[ ]` is open and `[x]` is completed. A linked task
record status is metadata-only during this transition. Any disagreement between
checkbox state and record status is diagnostic-only; the scanner never writes either
source.

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
input findings), `message`, and the source locator. Diagnostics may additionally
include safe `link_destination` and `linked_record_path` values. They must never put
host-absolute paths, file contents other than the excerpt, or database identifiers in
the result. Codes in this phase are `MALFORMED_CHECKBOX`, `UNSAFE_TASK_LINK`,
`MISSING_TASK_RECORD`, `UNTYPED_TASK_RECORD`, `WRONG_TASK_RECORD_TYPE`, and
`DUPLICATE_LINKED_TASK_RECORD`.

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
