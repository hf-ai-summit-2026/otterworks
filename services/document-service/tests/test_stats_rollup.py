"""A replica that restarts inside a rollup window does not double that window."""

import asyncio
from datetime import UTC, datetime

import pytest
from pymongo.asynchronous.database import AsyncDatabase

from app.jobs import stats_rollup
from app.models.document import STATS_ROLLUPS

WINDOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def _rows(db: AsyncDatabase) -> int:
    return await db[STATS_ROLLUPS].count_documents({})


@pytest.mark.asyncio
async def test_same_host_rerun_reuses_its_row(db_session: AsyncDatabase) -> None:
    first = await stats_rollup.compute_rollup(db_session, WINDOW)
    again = await stats_rollup.compute_rollup(db_session, WINDOW)
    assert again.id == first.id
    assert await _rows(db_session) == 1


@pytest.mark.asyncio
async def test_other_host_still_writes_its_own_row(
    db_session: AsyncDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    await stats_rollup.compute_rollup(db_session, WINDOW)
    monkeypatch.setattr(stats_rollup.socket, "gethostname", lambda: "replica-b")
    await stats_rollup.compute_rollup(db_session, WINDOW)
    assert await _rows(db_session) == 2
    assert await stats_rollup.duplicate_windows(db_session, WINDOW) == 1


@pytest.mark.asyncio
async def test_loop_survives_duplicate_check_failure_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A committed rollup whose duplicate check then fails must not stop the scheduler."""

    class Row:
        documents_total = 1
        versions_total = 1

    rollups = 0

    async def ok_rollup(db: object, window: object) -> Row:
        nonlocal rollups
        rollups += 1
        return Row()

    async def broken_duplicates(db: object, since: object) -> int:
        raise RuntimeError("connection reset")

    real_sleep = asyncio.sleep

    async def instant_sleep(delay: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(stats_rollup, "compute_rollup", ok_rollup)
    monkeypatch.setattr(stats_rollup, "duplicate_windows", broken_duplicates)
    monkeypatch.setattr(stats_rollup.asyncio, "sleep", instant_sleep)
    task = asyncio.create_task(stats_rollup.loop(object()))  # type: ignore[arg-type]
    for _ in range(40):
        await real_sleep(0)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert rollups > 1
