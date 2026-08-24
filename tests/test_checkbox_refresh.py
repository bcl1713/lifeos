"""Regression coverage for non-mutating checkbox scan reconciliation."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lifeos.checkbox_refresh import CheckboxRefreshCoordinator, WatchdogCheckboxRefreshWatcher
from lifeos.wiki_checkbox_tasks import scan_checkbox_tasks


def _write_checkbox(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_refresh_scans_current_files_after_atomic_replace_rename_and_delete_without_writes(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    original = _write_checkbox(wiki, "01-Projects/Alpha/old.md", "- [ ] old\n")
    coordinator = CheckboxRefreshCoordinator(wiki, interval_seconds=60)

    before = {path: path.read_bytes() for path in wiki.rglob("*") if path.is_file()}
    first = coordinator.refresh_once()
    replacement = original.with_suffix(".replacement")
    replacement.write_text("- [x] replacement\n", encoding="utf-8")
    replacement.replace(original)
    renamed = original.with_name("renamed.md")
    original.rename(renamed)
    second = coordinator.refresh_once()
    renamed.unlink()
    third = coordinator.refresh_once()

    assert [task.label for task in first.tasks] == ["old"]
    assert [(task.source_path, task.checked, task.label) for task in second.tasks] == [
        ("01-Projects/Alpha/renamed.md", True, "replacement")
    ]
    assert third.tasks == ()
    assert before[original] == b"- [ ] old\n"
    assert coordinator.last_result == third


def test_periodic_scan_recovers_a_missed_watcher_event(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = _write_checkbox(wiki, "dailies/today.md", "- [ ] before\n")
    coordinator = CheckboxRefreshCoordinator(wiki, interval_seconds=0.01)

    async def run() -> None:
        task = asyncio.create_task(coordinator.run())
        try:
            await asyncio.sleep(0.03)
            source.write_text("- [x] after\n", encoding="utf-8")
            await asyncio.sleep(0.04)
        finally:
            await coordinator.stop()
            await task

    asyncio.run(run())

    assert coordinator.refresh_count >= 2
    assert coordinator.last_result is not None
    assert [(task.checked, task.label) for task in coordinator.last_result.tasks] == [(True, "after")]


def test_watcher_event_bursts_debounce_to_one_requested_scan(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _write_checkbox(wiki, "dailies/today.md", "- [ ] observe\n")
    coordinator = CheckboxRefreshCoordinator(wiki, interval_seconds=60, debounce_seconds=0.02)

    async def run() -> None:
        task = asyncio.create_task(coordinator.run())
        try:
            await asyncio.sleep(0.02)
            assert coordinator.refresh_count == 1
            for _ in range(8):
                coordinator.request_refresh()
            await asyncio.sleep(0.06)
            assert coordinator.refresh_count == 2
        finally:
            await coordinator.stop()
            await task

    asyncio.run(run())


@pytest.mark.parametrize("unavailable_error", (ImportError, OSError))
def test_unavailable_watcher_never_prevents_periodic_reconciliation(
    tmp_path: Path, unavailable_error: type[Exception]
) -> None:
    wiki = tmp_path / "wiki"
    source = _write_checkbox(wiki, "dailies/today.md", "- [ ] observe\n")
    source_before = source.read_bytes()
    coordinator = CheckboxRefreshCoordinator(wiki, interval_seconds=0.01)
    watcher = WatchdogCheckboxRefreshWatcher(
        wiki,
        enabled=True,
        observer_factory=lambda handler, root: (_ for _ in ()).throw(unavailable_error()),
    )

    assert watcher.start(coordinator.request_refresh) is False
    assert watcher.diagnostic == f"unavailable: {unavailable_error.__name__}"

    async def run() -> None:
        task = asyncio.create_task(coordinator.run())
        try:
            await asyncio.sleep(0.04)
        finally:
            await coordinator.stop()
            await task

    asyncio.run(run())

    assert coordinator.refresh_count >= 2
    assert coordinator.last_result == scan_checkbox_tasks(wiki)
    assert source.read_bytes() == source_before


def test_restarted_coordinator_immediately_scans_current_wiki_state_after_prior_stop(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = _write_checkbox(wiki, "dailies/today.md", "- [ ] before restart\n")
    first = CheckboxRefreshCoordinator(wiki, interval_seconds=60)

    async def scan_and_stop(coordinator: CheckboxRefreshCoordinator) -> None:
        task = asyncio.create_task(coordinator.run())
        try:
            while coordinator.last_result is None:
                await asyncio.sleep(0)
        finally:
            await coordinator.stop()
            await task

    asyncio.run(scan_and_stop(first))
    assert first.last_result is not None
    assert [(task.checked, task.label) for task in first.last_result.tasks] == [(False, "before restart")]

    source.write_text("- [x] after restart\n", encoding="utf-8")
    source_before_second_scan = source.read_bytes()
    second = CheckboxRefreshCoordinator(wiki, interval_seconds=60)
    asyncio.run(scan_and_stop(second))

    assert second.last_result is not None
    assert [(task.checked, task.label) for task in second.last_result.tasks] == [(True, "after restart")]
    assert source.read_bytes() == source_before_second_scan


def test_watcher_overflow_requests_the_same_debounced_scan(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _write_checkbox(wiki, "dailies/today.md", "- [ ] observe\n")
    coordinator = CheckboxRefreshCoordinator(wiki, interval_seconds=60, debounce_seconds=0.01)
    watcher = WatchdogCheckboxRefreshWatcher(
        wiki,
        enabled=True,
        observer_factory=lambda handler, root: _OverflowObserver(handler),
    )

    async def run() -> None:
        task = asyncio.create_task(coordinator.run())
        try:
            await asyncio.sleep(0.02)
            assert watcher.start(coordinator.request_refresh) is True
            watcher.observer.emit_overflow()
            await asyncio.sleep(0.04)
            assert coordinator.refresh_count == 2
        finally:
            watcher.stop()
            await coordinator.stop()
            await task

    asyncio.run(run())


class _OverflowObserver:
    def __init__(self, handler) -> None:
        self.handler = handler

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def join(self) -> None:
        pass

    def emit_overflow(self) -> None:
        self.handler.on_any_event(object())
