import os

from fastapi import FastAPI

from lifeos import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="LifeOS", version=__version__)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "lifeos",
            "version": os.getenv("LIFEOS_VERSION", __version__),
        }

    return app


app = create_app()
