"""Non-mutating, scanner-authoritative checkbox refresh coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lifeos.wiki_checkbox_tasks import CheckboxTaskScanPolicy, CheckboxTaskScanResult, scan_checkbox_tasks


class CheckboxRefreshCoordinator:
    """Periodically scan a wiki; watcher events only request an earlier scan."""

    def __init__(
        self,
        wiki_root: str | Path,
        *,
        interval_seconds: float,
        debounce_seconds: float = 1.0,
        policy: CheckboxTaskScanPolicy | None = None,
        scanner: Callable[..., CheckboxTaskScanResult] = scan_checkbox_tasks,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if debounce_seconds < 0:
            raise ValueError("debounce_seconds must not be negative")
        self.wiki_root = Path(wiki_root)
        self.interval_seconds = interval_seconds
        self.debounce_seconds = debounce_seconds
        self.policy = policy
        self._scanner = scanner
        self._requested = asyncio.Event()
        self._stopped = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.last_result: CheckboxTaskScanResult | None = None
        self.last_error: Exception | None = None
        self.refresh_count = 0

    def refresh_once(self) -> CheckboxTaskScanResult:
        """Refresh only the in-memory observation; scanner owns all filesystem access."""
        result = self._scanner(self.wiki_root, policy=self.policy)
        self.last_result = result
        self.last_error = None
        self.refresh_count += 1
        return result

    def request_refresh(self) -> None:
        """Request a debounced scan; safe for calls from a watcher thread."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._requested.set)

    async def _refresh(self) -> None:
        try:
            await asyncio.to_thread(self.refresh_once)
        except Exception as error:
            self.last_error = error

    async def _wait_for_debounced_request(self) -> None:
        self._requested.clear()
        while True:
            try:
                await asyncio.wait_for(self._requested.wait(), timeout=self.debounce_seconds)
            except TimeoutError:
                return
            self._requested.clear()

    async def run(self) -> None:
        """Run an immediate recovery scan, then periodic and requested scans."""
        self._loop = asyncio.get_running_loop()
        await self._refresh()
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(self._requested.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                await self._refresh()
                continue
            await self._wait_for_debounced_request()
            if not self._stopped.is_set():
                await self._refresh()

    async def stop(self) -> None:
        self._stopped.set()
        self._requested.set()


class _CallbackEventHandler:
    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback

    def on_any_event(self, event: object) -> None:
        self.callback()


def _watchdog_observer(handler: _CallbackEventHandler, root: Path) -> Any:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class WatchdogHandler(FileSystemEventHandler):
        def on_any_event(self, event: object) -> None:
            handler.on_any_event(event)

    observer = Observer()
    observer.schedule(WatchdogHandler(), str(root), recursive=True)
    return observer


class WatchdogCheckboxRefreshWatcher:
    """Optional watchdog adapter that never scans or mutates data itself."""

    def __init__(
        self,
        wiki_root: str | Path,
        *,
        enabled: bool,
        observer_factory: Callable[[_CallbackEventHandler, Path], Any] | None = None,
    ) -> None:
        self.wiki_root = Path(wiki_root)
        self.enabled = enabled
        self._observer_factory = observer_factory or _watchdog_observer
        self.observer: Any | None = None
        self.diagnostic: str | None = None

    def start(self, callback: Callable[[], None]) -> bool:
        if not self.enabled:
            self.diagnostic = "disabled"
            return False
        try:
            self.observer = self._observer_factory(_CallbackEventHandler(callback), self.wiki_root)
            self.observer.start()
        except (ImportError, OSError) as error:
            self.observer = None
            self.diagnostic = f"unavailable: {error.__class__.__name__}"
            return False
        self.diagnostic = "active"
        return True

    def stop(self) -> None:
        if self.observer is not None:
            self.observer.stop()
            self.observer.join()
            self.observer = None
