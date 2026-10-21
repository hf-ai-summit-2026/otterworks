"""Async load generator and the background load process lifecycle."""

from __future__ import annotations

import asyncio
import os
import random
import signal
import statistics
import subprocess
import sys
import time
from typing import Any

import httpx

from .config import HERE, LIST_HANDLER, REPO, base_url, bearer, die, log, state_path
from .seed import _lorem


class Stats:
    def __init__(self) -> None:
        self.latencies: list[float] = []
        self.queries: list[int] = []
        self.errors = 0
        self.total = 0
        self.shed = 0

    def add(self, latency: float, status: int, queries: int | None) -> None:
        self.total += 1
        self.latencies.append(latency)
        if status >= 500:
            self.errors += 1
        if queries is not None:
            self.queries.append(queries)

    def line(self) -> str:
        if not self.latencies:
            return "no requests"
        lat = sorted(self.latencies)
        p50 = lat[len(lat) // 2]
        p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
        q = statistics.mean(self.queries) if self.queries else float("nan")
        return (
            f"n={self.total} p50={p50 * 1000:.0f}ms p95={p95 * 1000:.0f}ms "
            f"queries/req={q:.1f} 5xx={self.errors / self.total:.1%} shed={self.shed}"
        )

    def reset(self) -> None:
        self.__init__()


async def _drive(
    cat: dict[str, Any], scenario: str, duration: float | None, scale: float = 1.0
) -> None:
    sc = cat["scenarios"][scenario]
    profiles = sc.get("load") or {}
    if not profiles:
        log(f"{scenario}: no load profile; nothing to drive")
        return
    name, prof = next(iter(profiles.items()))
    owner = cat["seed"]["owner_id"]
    headers = bearer(owner)
    rps = float(prof["rps"]) * scale
    concurrency = max(1, round(int(prof["concurrency"]) * scale))
    stats = Stats()
    stop = asyncio.Event()

    def _stop(*_: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    async with httpx.AsyncClient(base_url=base_url(cat), headers=headers, timeout=30) as client:
        # (id, title) so an edit keeps the document's own title; the seed is
        # idempotent on title and a renamed fixture would be re-created.
        docs: list[tuple[str, str]] = []
        if prof.get("flow") == "edit-then-export":
            r = await client.get(LIST_HANDLER, params={"owner_id": owner, "size": 100})
            r.raise_for_status()
            docs = [(d["id"], d["title"]) for d in r.json()["items"]]
            if not docs:
                die("edit-then-export load needs seeded documents; run `incident.py seed`")

        sem = asyncio.Semaphore(concurrency)
        rng = random.Random(cat["seed"]["random_seed"])

        async def one(i: int) -> None:
            async with sem:
                t0 = time.perf_counter()
                try:
                    if prof.get("flow") == "edit-then-export":
                        doc_id, title = docs[i % len(docs)]
                        r = await client.put(
                            f"{LIST_HANDLER}{doc_id}",
                            json={
                                "title": title,
                                "content": _lorem(rng, cat["seed"]["words_per_document"]),
                                "content_type": "text/markdown",
                                "folder_id": cat["seed"]["folder_id"],
                            },
                        )
                        if r.status_code == 200:
                            r = await client.get(
                                f"{LIST_HANDLER}{doc_id}/export",
                                params={"format": "html"},
                            )
                    else:
                        params = dict(prof.get("params") or {})
                        params["owner_id"] = owner
                        r = await client.request(prof["method"], prof["path"], params=params)
                    q = r.headers.get("X-DB-Queries")
                    stats.add(time.perf_counter() - t0, r.status_code, int(q) if q else None)
                except httpx.HTTPError:
                    stats.add(time.perf_counter() - t0, 599, None)

        log(
            f"load[{scenario}/{name}]: {rps:g} rps, concurrency {concurrency}"
            + (f" (INCIDENT_LOAD_SCALE={scale:g})" if scale != 1 else "")
            + f", target {base_url(cat)}"
        )
        started = time.monotonic()
        last_report = started
        i = 0
        tasks: set[asyncio.Task[None]] = set()
        while not stop.is_set():
            if duration and time.monotonic() - started >= duration:
                break
            if sem.locked():
                stats.shed += 1
            else:
                t = asyncio.create_task(one(i))
                tasks.add(t)
                t.add_done_callback(tasks.discard)
                i += 1
            await asyncio.sleep(1.0 / rps)
            if time.monotonic() - last_report >= 5:
                log(f"load[{scenario}]: {stats.line()}")
                stats.reset()
                last_report = time.monotonic()
        await asyncio.gather(*tasks, return_exceptions=True)
        log(f"load[{scenario}]: final {stats.line()}")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def background_load_pid() -> int | None:
    """PID of the running background load generator, or None when none is alive."""
    p = state_path("load.pid")
    if not p.exists():
        return None
    pid = int(p.read_text().strip() or 0)
    return pid if _pid_alive(pid) else None


def start_background_load(scenario: str) -> int:
    # Re-arming must never strand the previous generator: one load process at a time.
    stop_background_load()
    logf = state_path(f"load-{scenario}.log").open("ab")
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "incident.py"), "load", scenario],
        cwd=REPO,
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    state_path("load.pid").write_text(str(proc.pid))
    log(f"load: started pid {proc.pid} (log: {logf.name})")
    return proc.pid


def stop_background_load() -> None:
    p = state_path("load.pid")
    if not p.exists():
        return
    pid = int(p.read_text().strip() or 0)
    try:
        os.killpg(pid, signal.SIGTERM)
        log(f"load: stopped pid {pid}")
        deadline = time.monotonic() + 10
        while _pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.2)
        if _pid_alive(pid):
            os.killpg(pid, signal.SIGKILL)
            log(f"load: pid {pid} did not exit on SIGTERM; killed")
    except ProcessLookupError:
        log(f"load: pid {pid} already gone")
    p.unlink(missing_ok=True)
