import json
from pathlib import Path

from lifeos.wiki_store import WikiRepository


def audit_wiki(root: str | Path) -> dict[str, object]:
    repository = WikiRepository(root)
    records = repository.list_records()
    by_id: dict[str, list[str]] = {}
    for record in records:
        if record.record_id:
            by_id.setdefault(record.record_id, []).append(record.path)
    duplicates = {record_id: paths for record_id, paths in by_id.items() if len(paths) > 1}
    return {
        "root": str(repository.root),
        "total": len(records),
        "counts": {kind: sum(record.record_type == kind for record in records) for kind in ("project", "area", "goal", "routine", "task")},
        "duplicates": duplicates,
        "records": [{"type": r.record_type, "id": r.record_id, "title": r.title, "path": r.path, "hash": r.content_hash} for r in records],
        "valid": not duplicates,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki", default="/home/brian/wiki")
    args = parser.parse_args()
    print(json.dumps(audit_wiki(args.wiki), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
