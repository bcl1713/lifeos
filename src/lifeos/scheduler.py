import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def generate_due_once(app: FastAPI, on: date) -> int:
    """Keep the scheduler inert while legacy recurrence awaits reviewed mapping."""
    return 0


async def _scheduler_loop(app: FastAPI) -> None:
    timezone = ZoneInfo(app.state.scheduler_timezone)
    interval = app.state.scheduler_interval_seconds
    while True:
        try:
            today = datetime.now(timezone).date()
            generated = await asyncio.to_thread(generate_due_once, app, today)
            if generated:
                logger.info("Skipped %s retired routine task occurrence(s)", generated)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Retired routine scheduler cycle failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def scheduler_lifespan(app: FastAPI):
    task = asyncio.create_task(_scheduler_loop(app), name="lifeos-retired-routine-scheduler")
    app.state.scheduler_task = task
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
