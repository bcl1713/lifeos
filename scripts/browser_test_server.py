"""Minimal authenticated LifeOS fixture server for browser regression tests."""

from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from lifeos.main import create_app


workspace = TemporaryDirectory()
root = Path(workspace.name)
wiki = root / "wiki"
note = wiki / "02-Areas/House/Index.md"
note.parent.mkdir(parents=True)
note.write_text("# House\n\nCanonical content. [Unsafe](javascript:alert(1))\n", encoding="utf-8")

app = create_app(
    database_url=f"sqlite:///{root / 'lifeos.db'}",
    auth_username="brian",
    auth_password="password",
    scheduler_enabled=False,
    wiki_root=str(wiki),
)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)
