# Controlled canonical task relocation

This is the operator runbook for `scripts/relocate_wiki_tasks.py`, delivered by implementation PR [#31](https://github.com/bcl1713/lifeos/pull/31). It applies only after that implementation is merged to `dev` and is present in the image or checkout being operated.

## Safety boundary

The canonical wiki is authoritative. Relocation changes a Task's canonical Markdown path and ownership fields; it is not an ordinary task edit. The tool is deliberately dry-run by default and has no automatic, scheduled, or broad live-migration mode.

**No real wiki apply is authorized by this runbook.** A later, explicit Brian gate must authorize a named wiki, backup set, mapping file, and maintenance window before anyone runs `--apply` against a real wiki. Until that gate, use only inventory, mapping rehearsal, and test-copy procedures.

Do not hand-edit `owner_type`, `owner_wiki_id`, or a task's canonical path to bypass this procedure. Do not use title similarity, source references, or current SQLite rows to infer ownership.

## CLI contract

Run the script with the database and wiki root that correspond to the same target. The defaults are `sqlite:///./data/lifeos.db`, `/wiki`, and `./data/task-relocation-journal`; explicitly set them when operating outside the application container.

```bash
python scripts/relocate_wiki_tasks.py \
  --database sqlite:////data/lifeos.db \
  --wiki-root /wiki
```

With no `--mapping`, this is an inventory-only dry run. It writes no canonical source, projection, backup, or journal. Its JSON includes active Task identity/path/hash, declared owner state, relationships, an owner candidate when resolvable, deterministic target path, per-task issues, path conflicts, and `ambiguous_or_unowned` IDs.

Supplying a mapping remains a dry run unless `--apply` is also supplied:

```bash
python scripts/relocate_wiki_tasks.py \
  --database sqlite:////data/lifeos.db \
  --wiki-root /wiki \
  --mapping /backups/relocation-mapping.json \
  --journal-dir /backups/task-relocation-journal
```

The mapping file must be either a JSON list or an object containing a `mappings` list. Every mapping must contain **exactly** these six non-empty string fields—no inferred or extra fields:

```json
{
  "source_id": "tsk-example",
  "source_path": "01-Projects/example/tasks/example-tsk-example.md",
  "source_hash": "<inventory content hash>",
  "owner_type": "project",
  "owner_wiki_id": "prj-example",
  "owner_path": "01-Projects/example/index.md"
}
```

`owner_type` must be `project` or `area`. Inbox/unowned relocation is intentionally not supported by this tool and requires later explicit policy. Generate mappings from the reviewed inventory; never synthesize them from task titles or source references.

A real mutation requires all of the following:

```bash
python scripts/relocate_wiki_tasks.py \
  --database sqlite:////data/lifeos.db \
  --wiki-root /wiki \
  --mapping /backups/relocation-mapping.json \
  --journal-dir /backups/task-relocation-journal \
  --backup-dir /backups/task-relocation-source-backups \
  --apply
```

`--apply` is rejected without both `--mapping` and `--backup-dir`. The backup directory is mandatory and must already be treated by the operator as a verified backup destination for this exact run. The tool creates a per-source Markdown backup there before moving that source, but it does not prove that a supplied directory is a complete wiki or SQLite backup. Verify the normal wiki archive and SQLite backup separately before the apply gate, retain their paths with the change record, and use a new empty per-run source-backup directory so an existing backup filename stops the run rather than being overwritten.

## Preflight stop conditions

A mapping rehearsal performs the same validation as apply without writes. It must succeed before an authorized apply. Stop and correct the mapping/source when any of the following occurs:

- the mapping fields are not exactly the six required fields, or a value is empty;
- the source ID is missing, inactive, duplicated among active tasks, has a changed path, or has a changed content hash;
- the owner ID does not resolve to the declared Project/Area type, or its canonical path no longer matches `owner_path`;
- the deterministic destination escapes the wiki root, already exists, is a symlink, or conflicts with another canonical file;
- the source has disappeared, escapes the root, is a symlink, or is not a regular file;
- an unfinished journal already exists for a mapped source; recover it before preparing a new mapping.

The tool does not choose an owner, merge destination content, overwrite a destination, or resolve duplicate active task IDs. A no-op mapping whose source is already at its deterministic owner path is reported as unchanged.

## Journal and recovery semantics

For each relocation, the tool writes an atomic JSON journal under `--journal-dir` and a source-file backup under `--backup-dir`. A persisted journal progresses through:

1. `planned` — the source backup and intended source/destination/owner identity are recorded; the source has not completed relocation.
2. `source_moved` — the source file has moved with `os.replace`, the destination has been read back with the original stable Task ID and the requested owner fields, but projection refresh may still be unfinished.
3. `complete` — projection refresh completed and the journal is terminal.

Journal data records the stable source ID/path/hash, destination path, owner type/ID/path, and backup path. Completed journals are idempotent: recovery ignores them. Do not edit journals manually.

Use recovery only to reconcile an interruption after a source move:

```bash
python scripts/relocate_wiki_tasks.py \
  --database sqlite:////data/lifeos.db \
  --wiki-root /wiki \
  --journal-dir /backups/task-relocation-journal \
  --recover
```

`--recover` accepts no `--mapping`. It refuses to guess: if the source still exists, rerun the original mapping after investigation; if neither a safe destination nor source exists, or destination identity/owner identity does not match the journal, stop and escalate. For a safe moved destination, recovery restores the requested owner fields if needed, refreshes the projection, and marks the journal complete.

## Authorized future procedure

This section describes the order required **after** the explicit Brian gate; it is not authorization to perform it now.

1. Record the gate, exact target/wiki root, mapping-file hash, maintenance window, and operator.
2. Take and verify fresh normal wiki and SQLite backups. Preserve the backup paths and verify the SQLite backup with `scripts/verify_backup.py`.
3. Run `scripts/sync_wiki_projection.py --check`; stop for any reconciliation failure, including `invalid_task_owners`, duplicate/authority conflict, stale hash, missing identity, or path conflict.
4. Run the inventory command and save its JSON. Review every proposed ownership and relationship against canonical source.
5. Build the exact mapping JSON from that inventory, review it independently, and run the mapping dry run. Resolve every preflight conflict; do not proceed on warnings or a changed hash.
6. Confirm the per-run backup and journal directories are separate, writable, retained, and associated with the verified backup set.
7. Only under the explicit gate, run the `--apply` command above. Record its JSON output and every journal path. If it stops after a source move, do not rerun with a new mapping; use `--recover` once the destination/journal identity is verified.
8. Run `scripts/sync_wiki_projection.py --check` after relocation. Then rebuild or refresh only through the approved projection workflow and repeat `--check` until aligned. Verify the affected Task's canonical path, stable ID, owner fields, and relationships from source and the rebuilt projection.

## Rollback and reconciliation

There is no automatic rollback flag. A projection rollback cannot undo a filesystem move. If an authorized run must be rolled back, freeze further applies, retain the journal and all evidence, restore the affected canonical Markdown from the verified source backup or verified wiki archive through the approved operator process, then rebuild the SQLite projection from canonical source. Do not copy a file back over a live source or edit SQLite directly as an ad hoc rollback.

After any recovery or deliberate rollback, run the non-mutating reconciliation gate before reopening normal mutation:

```bash
python scripts/sync_wiki_projection.py \
  --database sqlite:////data/lifeos.db \
  --wiki-root /wiki \
  --check
```

The target is a source/projection-aligned result with exactly one active canonical Task record at the approved path, preserved stable ID and relationships, and no unresolved relocation journal. Keep the inventory, reviewed mapping, apply/recovery JSON, journal files, and verified backup references with the operator record.
