"""Synchronize typed wiki records into the rebuildable LifeOS projection."""
from __future__ import annotations

import argparse
import json

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.scripts_bridge import reconcile_wiki_projection, sync_wiki_projection
from lifeos.wiki_store import WikiRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="sqlite:///./data/lifeos.db")
    parser.add_argument("--wiki-root", default="/wiki")
    parser.add_argument("--check", action="store_true", help="Report alignment without changing the projection")
    args = parser.parse_args()
    engine = create_engine(args.database)
    initialize_database(engine)
    factory = create_session_factory(engine)
    repository = WikiRepository(args.wiki_root)
    with factory() as session:
        if args.check:
            result = reconcile_wiki_projection(session, repository)
        else:
            result = sync_wiki_projection(session, repository)
    print(json.dumps(result, sort_keys=True))
    return 0 if not args.check or result["aligned"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
