"""Scenario steps: arm, disarm and the conditions an armed scenario holds."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import redis

from .compose import (
    compose,
    container_memory_limit,
    container_running,
    parse_size,
    purge_request_log,
    recreate_document_service,
    wait_healthy,
)
from .config import (
    die,
    load_catalog,
    load_scale,
    log,
    read_state,
    redis_url,
    sink_url,
    state_path,
    write_state,
)
from .fingerprint import fingerprints, git_sha
from .load import start_background_load, stop_background_load
from .prom import wait_alert_inactive
from .seed import seed


def _step_parts(step: Any) -> tuple[str, Any]:
    if isinstance(step, dict):
        ((kind, arg),) = step.items()
        return kind, arg
    return step, None


def arm_conditions(cat: dict[str, Any], sc: dict[str, Any]) -> list[tuple[str, bool]]:
    """(label, holds) for every incident-producing condition the scenario's arm steps create.

    The after gate re-checks these so a fix is only ever judged with the flaw's
    trigger still in place: flags set, memory ceiling applied, replica running.
    """
    conds: list[tuple[str, bool]] = []
    for step in sc["arm"]:
        kind, arg = _step_parts(step)
        match kind:
            case "flag":
                conds.append((f"chaos flag {arg} is set", flag_is_set(cat, str(arg))))
            case "memory-limit":
                want = parse_size(str(arg))
                have = container_memory_limit("document-service")
                conds.append(
                    (f"document-service memory limit is {arg} (have {have})", have == want)
                )
            case "start-replica":
                conds.append(
                    (
                        "document-service-replica is running",
                        container_running("document-service-replica"),
                    )
                )
    return conds


def flag_is_set(cat: dict[str, Any], key: str) -> bool:
    try:
        return bool(redis.Redis.from_url(redis_url(cat), socket_timeout=2).exists(key))
    except redis.RedisError:
        return False


def set_flag(cat: dict[str, Any], key: str, on: bool) -> None:
    r = redis.Redis.from_url(redis_url(cat))
    if on:
        r.set(key, "1", ex=4 * 3600)
    else:
        r.delete(key)
    log(f"flag {key} -> {'on' if on else 'off'}")


def run_step(cat: dict[str, Any], scenario: str, step: Any) -> None:
    if isinstance(step, dict):
        ((kind, arg),) = step.items()
    else:
        kind, arg = step, None
    match kind:
        case "seed":
            asyncio.run(seed(cat))
        case "load":
            start_background_load(scenario)
        case "stop-load":
            stop_background_load()
        case "flag":
            set_flag(cat, arg, True)
        case "unflag":
            set_flag(cat, arg, False)
        case "restart-document-service":
            compose("restart", "document-service")
            wait_healthy(cat)
        case "purge-request-log":
            purge_request_log(cat)
        case "memory-limit":
            recreate_document_service(cat, str(arg))
        case "restore-memory-limit":
            recreate_document_service(cat, None)
        case "start-replica":
            compose(
                "--profile",
                "double-run",
                "up",
                "-d",
                "--no-build",
                "--force-recreate",
                "document-service-replica",
            )
        case "stop-replica":
            compose("--profile", "double-run", "rm", "-sf", "document-service-replica", check=False)
        case "purge-duplicate-rollups":
            compose(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "otterworks",
                "-d",
                "otterworks",
                "-c",
                "DELETE FROM document_stats_rollups a USING document_stats_rollups b "
                "WHERE a.id > b.id AND a.window_start = b.window_start;",
                check=False,
            )
            compose("restart", "document-service", check=False)
        case _:
            die(f"unknown step {kind!r} in scenario {scenario}")


def cmd_arm(args: argparse.Namespace) -> None:
    cat = load_catalog()
    if args.scenario not in cat["scenarios"]:
        die(f"unknown scenario {args.scenario}; choose from {', '.join(cat['scenarios'])}")
    state = read_state()
    if state.get("scenario") and state["scenario"] != args.scenario:
        die(f"{state['scenario']} is already armed; run `incident.py disarm` first")
    sc = cat["scenarios"][args.scenario]
    scale = load_scale()
    log(f"arming {args.scenario}: {sc['title']}")
    wait_healthy(cat)
    wait_alert_inactive(cat, sc["alert"]["name"], float(sc["alert"]["resolves_within_seconds"]))
    for step in sc["arm"]:
        run_step(cat, args.scenario, step)
    write_state(
        {
            "scenario": args.scenario,
            "armed_at": datetime.now(UTC).isoformat(),
            "git_sha": git_sha(),
            "load_scale": scale,
            "fingerprints": fingerprints(),
        }
    )
    alert = sc["alert"]
    log(
        f"armed. expect alert {alert['name']} to fire within {alert['fires_within_seconds']}s; "
        f"watch with `incident.py status`"
    )


def cmd_disarm(_: argparse.Namespace) -> None:
    cat = load_catalog()
    state = read_state()
    scenarios = [state["scenario"]] if state.get("scenario") else list(cat["scenarios"])
    stop_background_load()
    for name in scenarios:
        for step in cat["scenarios"][name]["disarm"]:
            run_step(cat, name, step)
    state_path("armed.json").unlink(missing_ok=True)
    try:
        httpx.delete(f"{sink_url(cat)}/", timeout=5)
        log("alert sink cleared")
    except httpx.HTTPError as exc:
        log(f"alert sink not reachable ({exc}); skipping")
    log("disarmed")
