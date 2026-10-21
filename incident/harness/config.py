"""Catalog loading, INCIDENT_* target overrides, and shared runtime helpers."""

from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
import yaml

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
SCENARIOS_FILE = HERE / "scenarios.yaml"
EXPECTED_FILE = HERE / "expected.yaml"
STATE_DIR = HERE / ".state"
REPORT_DIR = HERE / "reports"
SERVICE_DIR = REPO / "services" / "document-service"

COMPOSE = os.environ.get(
    "INCIDENT_COMPOSE",
    "docker compose -f docker-compose.yml -f docker-compose.infra.yml "
    "-f docker-compose.incident.yml",
).split()


DEFAULT_SOAK_SECONDS = 150.0


def load_catalog() -> dict[str, Any]:
    with SCENARIOS_FILE.open() as fh:
        return yaml.safe_load(fh)


def target(cat: dict[str, Any], key: str, env: str) -> str:
    return os.environ.get(env) or cat["targets"][key]


def base_url(cat: dict[str, Any]) -> str:
    return target(cat, "document_service", "INCIDENT_BASE_URL").rstrip("/")


def prom_url(cat: dict[str, Any]) -> str:
    return target(cat, "prometheus", "INCIDENT_PROM_URL").rstrip("/")


def sink_url(cat: dict[str, Any]) -> str:
    return target(cat, "alert_sink", "INCIDENT_SINK_URL").rstrip("/")


def redis_url(cat: dict[str, Any]) -> str:
    return target(cat, "redis", "INCIDENT_REDIS_URL")


def load_scale() -> float:
    raw = os.environ.get("INCIDENT_LOAD_SCALE", "1")
    try:
        scale = float(raw)
    except ValueError:
        scale = 0.0
    if not math.isfinite(scale) or scale <= 0:
        die(f"INCIDENT_LOAD_SCALE must be a positive finite number, got {raw!r}")
    return scale


def jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "otterworks-local-dev-jwt-secret-change-me-in-production")


def bearer(user_id: str) -> dict[str, str]:
    token = jwt.encode(
        {"user_id": user_id, "sub": user_id, "exp": int(time.time()) + 6 * 3600},
        jwt_secret(),
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def log(msg: str) -> None:
    print(f"[incident {datetime.now(UTC).strftime('%H:%M:%S')}] {msg}", flush=True)


def die(msg: str, code: int = 2) -> None:
    print(f"[incident] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def state_path(name: str) -> Path:
    STATE_DIR.mkdir(exist_ok=True)
    return STATE_DIR / name


def read_state() -> dict[str, Any]:
    p = state_path("armed.json")
    return json.loads(p.read_text()) if p.exists() else {}


def write_state(state: dict[str, Any]) -> None:
    state_path("armed.json").write_text(json.dumps(state, indent=2))


LIST_HANDLER = "/api/v1/documents/"
