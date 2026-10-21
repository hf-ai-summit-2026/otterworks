"""Docker Compose wrappers for the local incident stack."""

from __future__ import annotations

import contextlib
import os
import subprocess
import time
from typing import Any

import httpx

from .config import COMPOSE, REPO, base_url, die, log
from .prom import METRIC_EXPRS, _fmt, prom_scalar


def sh(
    *args: str,
    check: bool = True,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    log("$ " + " ".join(args))
    return subprocess.run(
        args,
        cwd=REPO,
        check=check,
        text=True,
        capture_output=capture,
        env={**os.environ, **env} if env else None,
    )


def compose(
    *args: str, check: bool = True, capture: bool = False, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return sh(*COMPOSE, *args, check=check, capture=capture, env=env)


def recreate_document_service(cat: dict[str, Any], memory_limit: str | None) -> None:
    """Recreate the document-service container with a scenario-specific memory ceiling.

    `None` restores the Compose default (`INCIDENT_MEMORY_LIMIT` or 512m).
    """
    env = {"INCIDENT_MEMORY_LIMIT": memory_limit} if memory_limit else None
    compose("up", "-d", "--no-build", "--force-recreate", "document-service", env=env)
    wait_healthy(cat)
    log(f"document-service memory limit -> {memory_limit or 'default'}")


def container_id(service: str) -> str | None:
    out = compose("ps", "-q", "-a", service, capture=True, check=False).stdout.strip()
    return out.splitlines()[0] if out else None


def container_inspect(service: str, fmt: str) -> str | None:
    cid = container_id(service)
    if not cid:
        return None
    out = sh("docker", "inspect", "--format", fmt, cid, capture=True, check=False)
    return out.stdout.strip() if out.returncode == 0 else None


def container_running(service: str) -> bool:
    return container_inspect(service, "{{.State.Running}}") == "true"


def container_memory_limit(service: str) -> int | None:
    raw = container_inspect(service, "{{.HostConfig.Memory}}")
    return int(raw) if raw and raw.isdigit() else None


_SIZE_UNITS = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def parse_size(spec: str) -> int:
    spec = str(spec).strip().lower()
    unit = spec[-1] if spec[-1] in _SIZE_UNITS else "b"
    digits = spec[:-1] if spec[-1] in _SIZE_UNITS else spec
    return int(digits) * _SIZE_UNITS[unit]


REQUEST_LOG_DIR = "/var/log/otterworks/document-service"


def purge_request_log(cat: dict[str, Any]) -> None:
    """Delete the request-log files inside the container's tmpfs and prove the gauge fell to zero.

    A restart alone does not free the volume: the tmpfs is a container mount and
    outlives the process, so the next run would start with a full disk.
    """
    compose(
        "exec",
        "-T",
        "document-service",
        "sh",
        "-c",
        f"find {REQUEST_LOG_DIR} -mindepth 1 -type f -delete",
        check=False,
    )
    compose("restart", "document-service")
    wait_healthy(cat)
    remaining = compose(
        "exec",
        "-T",
        "document-service",
        "sh",
        "-c",
        f"find {REQUEST_LOG_DIR} -mindepth 1 -type f -printf '%s\\n' 2>/dev/null"
        " | awk '{s+=$1} END {print s+0}'",
        capture=True,
        check=False,
    ).stdout.strip()
    if remaining not in ("", "0"):
        die(f"purge-request-log: {remaining} bytes still in {REQUEST_LOG_DIR} after purge")
    ratio = None
    with contextlib.suppress(Exception):
        ratio = prom_scalar(cat, METRIC_EXPRS["request_log_ratio"])
    log(f"purge-request-log: {REQUEST_LOG_DIR} emptied (bytes=0, gauge ratio={_fmt(ratio)})")


def reset_fixture(cat: dict[str, Any]) -> None:
    """Delete the fixture owner's documents (versions/comments cascade) so `seed` starts clean."""
    owner = cat["seed"]["owner_id"]
    sql = (
        f"WITH gone AS (DELETE FROM documents WHERE owner_id = '{owner}' RETURNING 1) "
        "SELECT count(*) FROM gone"
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
    )
    log(f"reset-fixture: deleted {out.stdout.strip() or '0'} documents for owner {owner}")


def wait_healthy(cat: dict[str, Any], timeout: float = 90) -> None:
    url = base_url(cat) + "/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    die(f"document-service not healthy at {url} after {timeout:.0f}s")
