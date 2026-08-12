import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import WikiContextItem


def _frontmatter(text: str) -> dict[str, object]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    values: dict[str, object] = {}
    for line in text[4:end].splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"')
        if value.startswith("[") and value.endswith("]"):
            values[key.strip()] = [part.strip().strip("\"'") for part in value[1:-1].split(",") if part.strip()]
        else:
            values[key.strip()] = value
    return values


def _item(path: Path, wiki_root: Path) -> dict[str, object] | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    relative = path.relative_to(wiki_root).as_posix()
    if path.name.lower() != "index.md":
        return None
    parts = relative.split("/")
    if len(parts) != 3 or parts[0] not in {"01-Projects", "02-Areas"}:
        return None
    metadata = _frontmatter(text)
    source_type = "project" if parts[0] == "01-Projects" else "area"
    source_id = str(metadata.get("id") or relative.removesuffix("/index.md").replace("/", "-")).strip()
    title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.parent.name)
    aliases = metadata.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    status = str(metadata.get("status") or "active")
    body = text.split("---", 2)[-1].strip() if text.startswith("---") else text.strip()
    summary = next((line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")), "")
    stat = path.stat()
    return {
        "source_type": source_type,
        "source_id": source_id,
        "title": title,
        "wiki_path": relative,
        "wiki_url": f"/sources/wiki/{relative}",
        "status": status,
        "aliases": json.dumps(aliases),
        "summary": summary[:1000],
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc),
    }


def sync_wiki_context(database_url: str, wiki_root: str | Path) -> dict[str, int]:
    root = Path(wiki_root).resolve()
    engine = create_engine(database_url)
    initialize_database(engine)
    factory = create_session_factory(engine)
    discovered = {item["source_id"]: item for path in root.rglob("index.md") if (item := _item(path, root))}
    counts = {"created": 0, "updated": 0, "stale": 0, "unchanged": 0}
    with factory() as session:
        existing = {item.source_id: item for item in session.scalars(select(WikiContextItem))}
        for source_id, values in discovered.items():
            current = existing.get(source_id)
            if current is None:
                session.add(WikiContextItem(**values))
                counts["created"] += 1
            elif current.content_hash == values["content_hash"] and not current.stale:
                counts["unchanged"] += 1
            else:
                for key, value in values.items():
                    setattr(current, key, value)
                current.stale = False
                counts["updated"] += 1
        for source_id, current in existing.items():
            if source_id not in discovered and not current.stale:
                current.stale = True
                counts["stale"] += 1
        session.commit()
    return counts


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="sqlite:///./data/lifeos.db")
    parser.add_argument("--wiki-root", default="/wiki")
    args = parser.parse_args()
    print(json.dumps(sync_wiki_context(args.database, args.wiki_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
