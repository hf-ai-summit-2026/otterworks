"""Prometheus and alert-sink queries: alert state, firing time and the metrics behind the gates."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .config import LIST_HANDLER, die, log, prom_url, sink_url


def prom_query(cat: dict[str, Any], expr: str) -> list[dict[str, Any]]:
    r = httpx.get(f"{prom_url(cat)}/api/v1/query", params={"query": expr}, timeout=10)
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"prometheus: {body}")
    return body["data"]["result"]


def prom_scalar(cat: dict[str, Any], expr: str) -> float | None:
    res = prom_query(cat, expr)
    if not res:
        return None
    try:
        return float(res[0]["value"][1])
    except (KeyError, ValueError, IndexError):
        return None


def prom_alerts(cat: dict[str, Any]) -> list[dict[str, Any]]:
    r = httpx.get(f"{prom_url(cat)}/api/v1/alerts", timeout=10)
    r.raise_for_status()
    return r.json()["data"]["alerts"]


def devin_page_for(
    cat: dict[str, Any], alertname: str, since: str | None = None
) -> dict[str, Any] | None:
    """Newest delivery to the Devin receiver that is a firing page for `alertname`.

    `since` (ISO-8601, UTC) drops captures from earlier runs of the same scenario.
    """
    try:
        r = httpx.get(f"{sink_url(cat)}/devin", timeout=5)
        deliveries = r.json() if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return None
    for rec in reversed(deliveries or []):
        if since and rec.get("received_at", "") < since:
            continue
        payload = rec.get("payload") or {}
        if payload.get("status") != "firing":
            continue
        if any(
            a.get("labels", {}).get("alertname") == alertname for a in payload.get("alerts", [])
        ):
            return rec
    return None


def alert_state(cat: dict[str, Any], name: str) -> str:
    states = [a["state"] for a in prom_alerts(cat) if a["labels"].get("alertname") == name]
    if "firing" in states:
        return "firing"
    if "pending" in states:
        return "pending"
    return "inactive"


def wait_alert_inactive(cat: dict[str, Any], name: str, budget: float) -> None:
    """Block until `name` is inactive, so the next arm's page is provably fresh.

    A scenario's alert can keep firing for minutes after disarm (rate windows,
    `for`); the before gate rejects any alert that crossed into firing before the
    arm time, so arming under a still-firing alert can only produce a red gate.
    """
    deadline = time.monotonic() + budget
    while (state := alert_state(cat, name)) != "inactive":
        if time.monotonic() >= deadline:
            die(f"{name} still {state} from an earlier run after {budget:.0f}s; let it resolve")
        log(f"{name} is still {state} from an earlier run; waiting for it to resolve before arming")
        time.sleep(10)


def _parse_ts(raw: str) -> datetime:
    # Prometheus emits RFC 3339 with nanoseconds; datetime accepts at most 6 digits.
    raw = re.sub(r"\.(\d{6})\d+", r".\1", raw).replace("Z", "+00:00")
    ts = datetime.fromisoformat(raw)
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def alert_fired_at(cat: dict[str, Any], name: str) -> datetime | None:
    """When the firing alert `name` crossed into firing: activeAt plus the rule's `for`.

    Prometheus only records when the alert became pending (`activeAt`); the rule's
    `duration` is what it had to hold before firing. Returns None when not firing.
    """
    active = [
        a
        for a in prom_alerts(cat)
        if a["labels"].get("alertname") == name and a["state"] == "firing"
    ]
    if not active:
        return None
    active_at = min(_parse_ts(a["activeAt"]) for a in active)
    r = httpx.get(f"{prom_url(cat)}/api/v1/rules", params={"type": "alert"}, timeout=10)
    r.raise_for_status()
    hold = 0.0
    for group in r.json()["data"]["groups"]:
        for rule in group["rules"]:
            if rule.get("name") == name:
                hold = float(rule.get("duration", 0))
    return active_at + timedelta(seconds=hold)


_LIST = f'job="document-service",handler="{LIST_HANDLER}",method="GET"'
_LIST_H = f'handler="{LIST_HANDLER}"'

METRIC_EXPRS = {
    "request_rate": f"sum(rate(http_requests_total{{{_LIST}}}[2m]))",
    "p95_seconds": (
        "histogram_quantile(0.95, sum by (le) "
        f"(rate(http_request_duration_seconds_bucket{{{_LIST}}}[2m])))"
    ),
    "error_ratio": (
        'sum(rate(http_requests_total{job="document-service",status=~"5.."}[2m])) '
        '/ sum(rate(http_requests_total{job="document-service"}[2m]))'
    ),
    "queries_per_request": (
        f"sum(rate(otterworks_db_queries_per_request_sum{{{_LIST_H}}}[2m])) "
        f"/ sum(rate(otterworks_db_queries_per_request_count{{{_LIST_H}}}[2m]))"
    ),
    "request_log_ratio": (
        "max(otterworks_request_log_bytes / otterworks_request_log_capacity_bytes)"
    ),
    "memory_ratio": (
        "max(otterworks_process_resident_memory_bytes "
        "/ (otterworks_process_memory_limit_bytes > 0))"
    ),
    "cache_entries": "max(otterworks_render_cache_entries)",
    "duplicate_windows": "max(otterworks_rollup_duplicate_windows)",
}


def snapshot_metrics(cat: dict[str, Any]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for key, expr in METRIC_EXPRS.items():
        try:
            out[key] = prom_scalar(cat, expr)
        except Exception as exc:  # noqa: BLE001 - keep going, report what we can
            log(f"prometheus query {key} failed: {exc}")
            out[key] = None
    return out


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.3f}"
