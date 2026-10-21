"""Scheduled document-stats rollup.

Every ``settings.rollup_interval_seconds`` the service snapshots document,
version and word totals into ``document_stats_rollups`` for the usage
dashboard. The schedule is aligned to wall-clock windows so restarts do not
shift the series.
"""

from __future__ import annotations

import asyncio
import socket
import time
from datetime import UTC, datetime, timedelta

import structlog
from pymongo.asynchronous.database import AsyncDatabase

from app.config import settings
from app.models.document import (
    DOCUMENT_VERSIONS,
    DOCUMENTS,
    STATS_ROLLUPS,
    DocumentStatsRollup,
)
from app.telemetry import ROLLUP_DUPLICATE_WINDOWS, ROLLUP_RUNS_TOTAL, SERVICE

logger = structlog.get_logger()

# Re-read the duplicate-window gauge this long after the rollup, so a duplicate
# committed by another replica after this process's own rollup is still reported
# from this process's /metrics.
DUPLICATE_RECHECK_DELAY_SECONDS = 10


def current_window(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    interval = settings.rollup_interval_seconds
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % interval, tz=UTC)


async def own_rollup(
    db: AsyncDatabase, window_start: datetime
) -> DocumentStatsRollup | None:
    """The row this host already wrote for `window_start`, if any."""
    doc = await db[STATS_ROLLUPS].find_one(
        {"window_start": window_start, "computed_by": socket.gethostname()}
    )
    return DocumentStatsRollup.from_doc(doc) if doc else None


async def compute_rollup(db: AsyncDatabase, window_start: datetime) -> DocumentStatsRollup:
    # A restart inside the window must not double the window: this host's own
    # earlier row wins. Rows other hosts wrote are not consulted here.
    if (done := await own_rollup(db, window_start)) is not None:
        return done

    live = {"is_deleted": False}
    documents_total = await db[DOCUMENTS].count_documents(live)
    words_cursor = await db[DOCUMENTS].aggregate(
        [{"$match": live}, {"$group": {"_id": None, "total": {"$sum": "$word_count"}}}]
    )
    words = await words_cursor.to_list(length=1)
    words_total = int(words[0]["total"]) if words else 0
    versions_total = await db[DOCUMENT_VERSIONS].count_documents({})

    row = DocumentStatsRollup(
        window_start=window_start,
        documents_total=documents_total,
        versions_total=versions_total,
        words_total=words_total,
        computed_by=socket.gethostname(),
    )
    await db[STATS_ROLLUPS].insert_one(row.to_doc())
    return row


async def duplicate_windows(db: AsyncDatabase, since: datetime) -> int:
    cursor = await db[STATS_ROLLUPS].aggregate(
        [
            {"$match": {"window_start": {"$gte": since}}},
            {"$group": {"_id": "$window_start", "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
            {"$count": "windows"},
        ]
    )
    dupes = await cursor.to_list(length=1)
    return int(dupes[0]["windows"]) if dupes else 0


async def refresh_duplicate_gauge(db: AsyncDatabase, window: datetime) -> int:
    dupes = await duplicate_windows(db, window - timedelta(hours=1))
    ROLLUP_DUPLICATE_WINDOWS.labels(SERVICE).set(dupes)
    return dupes


async def run_once(db: AsyncDatabase) -> None:
    window = current_window()
    try:
        row = await compute_rollup(db, window)
    except Exception:
        ROLLUP_RUNS_TOTAL.labels(SERVICE, "error").inc()
        logger.exception("stats_rollup_failed", window_start=window.isoformat())
        return
    ROLLUP_RUNS_TOTAL.labels(SERVICE, "success").inc()
    logger.info(
        "stats_rollup_completed",
        window_start=window.isoformat(),
        documents_total=row.documents_total,
        versions_total=row.versions_total,
    )
    await refresh_duplicate_gauge(db, window)


async def loop(db: AsyncDatabase) -> None:
    interval = settings.rollup_interval_seconds
    while True:
        # Fire a couple of seconds into each window so every replica lands in
        # the same window regardless of how the loop was started.
        delay = interval - (time.time() % interval) + 2
        await asyncio.sleep(delay)
        window = current_window()
        # The rollup itself is written inside run_once; nothing after that point
        # (the duplicate-window gauge is reporting only) may take the
        # scheduler down and stop future windows.
        try:
            await run_once(db)
            await asyncio.sleep(DUPLICATE_RECHECK_DELAY_SECONDS)
            await refresh_duplicate_gauge(db, window)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("stats_rollup_iteration_failed", window_start=window.isoformat())


def start(db: AsyncDatabase) -> asyncio.Task[None] | None:
    if not settings.rollup_enabled:
        return None
    logger.info("stats_rollup_scheduled", interval_seconds=settings.rollup_interval_seconds)
    return asyncio.create_task(loop(db), name="stats-rollup")
