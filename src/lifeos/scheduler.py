import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from lifeos.checkbox_refresh import CheckboxRefreshCoordinator, WatchdogCheckboxRefreshWatcher

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
    refresh_task: asyncio.Task[None] | None = None
    watcher: WatchdogCheckboxRefreshWatcher | None = None
    if app.state.wiki_repository is not None:
        coordinator = CheckboxRefreshCoordinator(
            app.state.wiki_repository.root,
            interval_seconds=app.state.checkbox_refresh_interval_seconds,
            debounce_seconds=app.state.checkbox_refresh_debounce_seconds,
            policy=app.state.checkbox_scan_policy,
        )
        app.state.checkbox_refresh_coordinator = coordinator
        refresh_task = asyncio.create_task(coordinator.run(), name="lifeos-checkbox-refresh")
        app.state.checkbox_refresh_task = refresh_task
        watcher = WatchdogCheckboxRefreshWatcher(
            app.state.wiki_repository.root, enabled=app.state.checkbox_watcher_enabled
        )
        app.state.checkbox_refresh_watcher = watcher
        if not watcher.start(coordinator.request_refresh):
            logger.info("Checkbox watcher %s; periodic scanner remains authoritative", watcher.diagnostic)
    try:
        yield
    finally:
        if watcher is not None:
            watcher.stop()
        if refresh_task is not None:
            await app.state.checkbox_refresh_coordinator.stop()
            await asyncio.gather(refresh_task, return_exceptions=True)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
