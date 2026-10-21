"""Status, alert simulation, and the fail-closed before/after gate with its reports."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
import traceback
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .compose import compose
from .config import (
    DEFAULT_SOAK_SECONDS,
    REPO,
    REPORT_DIR,
    die,
    load_catalog,
    log,
    prom_url,
    read_state,
    sink_url,
)
from .fingerprint import fingerprints, git_sha, load_expected
from .load import _drive, background_load_pid, start_background_load, stop_background_load
from .prom import (
    _fmt,
    _parse_ts,
    alert_fired_at,
    alert_state,
    devin_page_for,
    prom_alerts,
    snapshot_metrics,
)
from .scenarios import arm_conditions, run_step


def rollup_soak_metrics(since: datetime) -> dict[str, float | None]:
    """Rollup rows written since `since`: how many distinct windows, and how many duplicates.

    Read straight from Postgres so the double-run after gate proves both that
    the job kept running under two replicas and that no window was computed twice.
    """
    sql = (
        "SELECT count(DISTINCT window_start), count(*) - count(DISTINCT window_start) "
        f"FROM document_stats_rollups WHERE created_at >= '{since.isoformat()}'"
    )
    out = compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "otterworks",
        "-d",
        "otterworks",
        "-qtAc",
        sql,
        capture=True,
        check=False,
    )
    try:
        windows, dupes = (int(x) for x in out.stdout.strip().split("|"))
    except ValueError:
        return {"rollup_windows_new": None, "rollup_duplicates_new": None}
    return {"rollup_windows_new": float(windows), "rollup_duplicates_new": float(dupes)}


def cmd_status(_: argparse.Namespace) -> None:
    cat = load_catalog()
    state = read_state()
    print(f"armed: {state.get('scenario') or '-'}  (since {state.get('armed_at', '-')})")
    try:
        alerts = prom_alerts(cat)
    except httpx.HTTPError as exc:
        die(f"prometheus unreachable at {prom_url(cat)}: {exc}")
    paging = [a for a in alerts if a["labels"].get("page") == "devin"]
    other = len(alerts) - len(paging)
    if paging:
        print("alerts (page=devin):")
        for a in paging:
            print(f"  {a['state']:8} {a['labels']['alertname']:32} since {a.get('activeAt', '')}")
    else:
        print("alerts (page=devin): none")
    if other:
        print(f"  ({other} other alert(s) active; only page=devin alerts route to the responder)")
    print("metrics (2m window):")
    for k, v in snapshot_metrics(cat).items():
        print(f"  {k:22} {'-' if v is None else f'{v:.3f}'}")


def cmd_simulate_alert(args: argparse.Namespace) -> None:
    cat = load_catalog()
    url = f"{sink_url(cat)}/{args.receiver}/latest"
    r = httpx.get(url, timeout=10)
    r.raise_for_status()
    record = r.json()
    if record is None:
        die(f"nothing captured yet on receiver {args.receiver!r} (is an alert firing?)", 1)
    print(json.dumps(record, indent=2))


def _check(findings: list[str], ok: bool, msg: str) -> None:
    log(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        findings.append(msg)


NO_SAMPLES = (
    "no samples in the 2m window (Prometheus returned nan/none): the load never "
    "reached the service or its scrape target is down"
)


def _threshold_checks(
    findings: list[str], metrics: dict[str, float | None], thresholds: dict[str, float]
) -> None:
    for key, threshold in thresholds.items():
        metric, bound = key.rsplit("_", 1)
        val = metrics.get(metric)
        op = ">=" if bound == "min" else "<="
        if val is None or math.isnan(val):
            _check(findings, False, f"{metric} {op} {threshold}: {NO_SAMPLES}")
            continue
        ok = val >= threshold if bound == "min" else val <= threshold
        _check(findings, ok, f"{metric}={_fmt(val)} {op} {threshold}")


# Below this fraction of the profile's rps the alert's own rate precondition
# (> 1 rps) can be unmet, so an inactive alert proves nothing about the fix.
MIN_OFFERED_LOAD_FRACTION = 0.5


def _check_load_reached(
    findings: list[str], metrics: dict[str, float | None], sc: dict[str, Any]
) -> None:
    prof = next(iter(sc["load"].values()))
    if prof.get("flow") == "edit-then-export":
        return  # request_rate only covers the list handler
    rps = float(prof["rps"])
    floor = rps * MIN_OFFERED_LOAD_FRACTION
    rate = metrics.get("request_rate")
    if rate is None or math.isnan(rate):
        _check(findings, False, f"offered load reached the service: {NO_SAMPLES}")
        return
    _check(
        findings,
        rate >= floor,
        f"offered load reached the service: request_rate={rate:.2f} >= {floor:g} rps "
        f"(half the pinned {rps:g} rps profile; below this the host cannot sustain the "
        f"workload and the result is inconclusive, not a verdict on the fix)",
    )


def cmd_verify(args: argparse.Namespace) -> None:
    findings: list[str] = []
    started = time.monotonic()
    report: dict[str, Any] = {
        "scenario": args.scenario,
        "expect": args.expect,
        "started_at": datetime.now(UTC).isoformat(),
    }
    # A gate that crashes must still leave its evidence: anything that escapes
    # the checks (Prometheus down, a preparation step failing) becomes a RED
    # finding with the traceback in the report rather than a bare exception.
    try:
        _verify(args, report, findings, started)
    except Exception as exc:
        findings.append(f"verify aborted: {type(exc).__name__}: {exc}")
        report["traceback"] = traceback.format_exc()
        _finish(report, findings, started)


def _verify(
    args: argparse.Namespace, report: dict[str, Any], findings: list[str], started: float
) -> None:
    cat = load_catalog()
    if args.scenario not in cat["scenarios"]:
        die(f"unknown scenario {args.scenario}")
    sc = cat["scenarios"][args.scenario]
    expected = load_expected()
    fp = fingerprints()
    report["git_sha"] = git_sha()
    report["fingerprints"] = fp
    report["expected_fingerprints"] = expected.get("fingerprints", {})

    # 1. Fixture must be byte-identical to what was recorded -- always.
    _check(
        findings,
        fp["fixture"] == expected["fingerprints"]["fixture"],
        f"fixture fingerprint matches expected.yaml ({fp['fixture'][:12]})",
    )
    # 2. Source must match in the before-state; must differ in the after-state.
    same_source = fp["source"] == expected["fingerprints"]["source"]
    if args.expect == "before":
        _check(findings, same_source, "source fingerprint matches the recorded before-state")
    else:
        _check(
            findings,
            not same_source,
            "source fingerprint differs from the before-state (a fix is present)",
        )
    _check(
        findings,
        args.scenario in expected.get("scenarios", {}),
        f"scenario {args.scenario} is pinned in expected.yaml",
    )

    if findings and not args.keep_going:
        _finish(report, findings, started)

    # 3. Runtime. Both gates are judged relative to the armed scenario: the
    # before-state's time-to-fire is measured from `armed_at`, not from whenever
    # verify happened to start, so a late page cannot pass by waiting.
    alert = sc["alert"]
    armed = read_state()
    _check(
        findings,
        armed.get("scenario") == args.scenario,
        f"scenario {args.scenario} is armed "
        f"(the {args.expect}-state is judged under its conditions)",
    )
    if findings and not args.keep_going:
        _finish(report, findings, started)
    armed_at = _parse_ts(armed["armed_at"]) if armed.get("armed_at") else datetime.now(UTC)
    report["armed_at"] = armed_at.isoformat()
    if args.expect == "before":
        budget = float(alert["fires_within_seconds"])
        fire_deadline = armed_at + timedelta(seconds=budget)
        deadline = time.monotonic() + max(0.0, (fire_deadline - datetime.now(UTC)).total_seconds())
        fired_at = alert_fired_at(cat, alert["name"])
        while fired_at is None and time.monotonic() < deadline:
            time.sleep(10)
            fired_at = alert_fired_at(cat, alert["name"])
            log(
                f"waiting for {alert['name']}: {alert_state(cat, alert['name'])} "
                f"({int(deadline - time.monotonic())}s left)"
            )
        time_to_fire = (fired_at - armed_at).total_seconds() if fired_at else None
        report["alert_fired_at"] = fired_at.isoformat() if fired_at else None
        report["time_to_fire_seconds"] = time_to_fire
        _check(
            findings,
            fired_at is not None and armed_at <= fired_at <= fire_deadline,
            f"alert {alert['name']} fired {_fmt(time_to_fire)}s after arming "
            f"(budget {budget:.0f}s; a stale or late alert does not count)",
        )
        metrics = snapshot_metrics(cat)
        report["metrics"] = metrics
        _threshold_checks(findings, metrics, sc.get("before", {}))
        # Alertmanager batches for group_wait before it posts, so allow it the
        # rest of the alert budget (at least 60s); only a *firing* delivery that
        # names this scenario's alert counts, never a stale capture.
        captured = None
        deadline = max(deadline, time.monotonic() + 60)
        armed_iso = armed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        while captured is None and time.monotonic() < deadline:
            captured = devin_page_for(cat, alert["name"], since=armed_iso)
            if captured is None:
                time.sleep(5)
        report["devin_webhook_captured"] = captured is not None
        report["devin_webhook_received_at"] = captured and captured.get("received_at")
        _check(
            findings,
            captured is not None,
            f"Devin webhook receiver captured a firing {alert['name']} page",
        )
    else:
        # After a fix: the scenario must still be armed, so the fix is judged
        # under the same incident-producing conditions (flags, memory limit,
        # replica) and the same load. Then the alert must be inactive and every
        # scenario-specific after-threshold met.
        # The armed background generator is paused for the whole after-gate: the
        # prepare steps (log purge, restart) must not race live requests, and the
        # gate drives the scenario's profile itself so the offered load is exactly
        # the scenario's, not the profile twice. It is resumed afterwards, pass or
        # fail, so the scenario stays armed for the next attempt.
        had_background = background_load_pid() is not None
        stop_background_load()
        try:
            for step in sc.get("after_prepare", []):
                run_step(cat, args.scenario, step)
            for label, holds in arm_conditions(cat, sc):
                _check(findings, holds, label)
            if findings and not args.keep_going:
                _finish(report, findings, started)
            soak = float(
                args.soak
                if args.soak is not None
                else sc.get("after_soak_seconds", DEFAULT_SOAK_SECONDS)
            )
            report["soak_seconds"] = soak
            report["load_scale"] = 1.0
            soak_started = datetime.now(UTC)
            if sc.get("load"):
                asyncio.run(_drive(cat, args.scenario, duration=soak))
            else:
                log(f"soaking {soak:.0f}s under the armed conditions (no load profile)")
                time.sleep(soak)
            deadline = time.monotonic() + alert["resolves_within_seconds"]
            state = alert_state(cat, alert["name"])
            while state != "inactive" and time.monotonic() < deadline:
                time.sleep(10)
                state = alert_state(cat, alert["name"])
                log(f"waiting for {alert['name']} to clear: {state}")
            _check(
                findings,
                state == "inactive",
                f"alert {alert['name']} is inactive under the same conditions",
            )
            # The trigger must have held for the whole soak, not just at the
            # start: a chaos flag that expired mid-run would make an unfixed
            # flaw look quiet.
            for label, holds in arm_conditions(cat, sc):
                _check(findings, holds, f"{label} (still, after the soak)")
            metrics = snapshot_metrics(cat)
            if any(key.startswith("rollup_") for key in sc.get("after", {})):
                metrics.update(rollup_soak_metrics(soak_started))
            report["metrics"] = metrics
            if sc.get("load"):
                _check_load_reached(findings, metrics, sc)
            _threshold_checks(findings, metrics, sc.get("after", {}))
        finally:
            if had_background:
                start_background_load(args.scenario)

    _finish(report, findings, started)


def _finish(report: dict[str, Any], findings: list[str], started: float) -> None:
    report["findings"] = findings
    report["passed"] = not findings
    report["duration_seconds"] = round(time.monotonic() - started, 1)
    REPORT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPORT_DIR / f"{report['scenario']}-{report['expect']}-{stamp}.json"
    out.write_text(json.dumps(report, indent=2))
    verdict = "GREEN" if not findings else "RED"
    print(
        f"\nverify {report['scenario']} --expect {report['expect']}: {verdict}  "
        f"(report: {out.relative_to(REPO)})"
    )
    for f in findings:
        print(f"  - {f}")
    sys.exit(0 if not findings else 1)
