import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from lifeos.routine_service import generate_all_routines

logger = logging.getLogger(__name__)


def generate_due_once(app: FastAPI, on: date) -> int:
    with app.state.session_factory() as session:
        return generate_all_routines(session, on, "scheduler")


async def _scheduler_loop(app: FastAPI) -> None:
    timezone = ZoneInfo(app.state.scheduler_timezone)
    interval = app.state.scheduler_interval_seconds
    while True:
        try:
            today = datetime.now(timezone).date()
            generated = await asyncio.to_thread(generate_due_once, app, today)
            if generated:
                logger.info("Generated %s routine task occurrence(s)", generated)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Routine generation cycle failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def scheduler_lifespan(app: FastAPI):
    task = asyncio.create_task(_scheduler_loop(app), name="lifeos-routine-scheduler")
    app.state.scheduler_task = task
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
