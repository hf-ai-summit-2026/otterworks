"""Fixture and source fingerprints, and the audited expected.yaml they are pinned in."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from datetime import UTC, datetime
from typing import Any

import yaml

from .config import EXPECTED_FILE, REPO, die, load_catalog, log

# Inputs that change what a recorded run looks like. Source and fixture are
# fingerprinted separately: the fixture must never drift; the source is
# expected to differ between the before-state and a fix. The migration history
# that exists on the before-state is fixture (rewriting 001-003 would change the
# schema the recording was made against); a fix is allowed to *add* a migration,
# so the versions directory as a whole is source.
MIGRATIONS = "services/document-service/alembic/versions"
FIXTURE_INPUTS = [
    "incident/scenarios.yaml",
    "incident/incident.py",
    "incident/harness",
    "observability/prometheus/incident_alerts.yml",
    "observability/prometheus/prometheus.yml",
    "observability/alertmanager/alertmanager.yml.tmpl",
    "docker-compose.incident.yml",
    f"{MIGRATIONS}/001_initial_schema.py",
    f"{MIGRATIONS}/002_document_stats_rollups.py",
    f"{MIGRATIONS}/003_backfill_word_count.py",
]
SOURCE_INPUTS = [
    "services/document-service/app",
    MIGRATIONS,
    "services/document-service/Dockerfile",
    "services/document-service/pyproject.toml",
    "services/document-service/poetry.lock",
]


def git_sha() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
    )
    return out.stdout.strip() if out.returncode == 0 else "unknown"


def _hash_paths(rel_paths: list[str]) -> str:
    h = hashlib.sha256()
    for rel in rel_paths:
        p = REPO / rel
        files = sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else [p]
        for f in files:
            if "__pycache__" in f.parts or f.suffix == ".pyc":
                continue
            h.update(str(f.relative_to(REPO)).encode())
            h.update(b"\0")
            h.update(f.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


def fingerprints() -> dict[str, str]:
    return {"fixture": _hash_paths(FIXTURE_INPUTS), "source": _hash_paths(SOURCE_INPUTS)}


def load_expected() -> dict[str, Any]:
    if not EXPECTED_FILE.exists():
        die(f"{EXPECTED_FILE.relative_to(REPO)} missing; run `incident.py record --reason ...`")
    with EXPECTED_FILE.open() as fh:
        return yaml.safe_load(fh)


def cmd_fingerprint(_: argparse.Namespace) -> None:
    fp = fingerprints()
    print(yaml.safe_dump({"fingerprints": fp}, sort_keys=False).rstrip())
    if not EXPECTED_FILE.exists():
        return
    exp = load_expected()["fingerprints"]
    drifted = [k for k in ("fixture", "source") if exp.get(k) != fp[k]]
    for k in ("fixture", "source"):
        print(f"{k}: {'DIFFERS from' if k in drifted else 'matches'} expected.yaml")
    if drifted:
        die(
            f"{', '.join(drifted)} fingerprint drifted from expected.yaml "
            "(expected in the after-state; in the before-state it means something "
            "other than the fix changed -- do not `record` past it)"
        )


def cmd_record(args: argparse.Namespace) -> None:
    if not args.reason or len(args.reason.strip()) < 10:
        die("--reason is required (>= 10 characters) and is written into expected.yaml")
    cat = load_catalog()
    doc = {
        "recorded": {
            "at": datetime.now(UTC).isoformat(),
            "git_sha": git_sha(),
            "reason": args.reason.strip(),
        },
        "fingerprints": fingerprints(),
        "scenarios": {
            name: {
                "alert": sc["alert"]["name"],
                "fires_within_seconds": sc["alert"]["fires_within_seconds"],
            }
            for name, sc in cat["scenarios"].items()
        },
    }
    header = (
        "# Recorded before-state for the incident-responder gate. Do not edit by hand;\n"
        '# re-pin with `make incident-record REASON="..."` -- the reason is kept here\n'
        "# so every re-record is auditable in git history.\n"
    )
    EXPECTED_FILE.write_text(header + yaml.safe_dump(doc, sort_keys=False))
    log(f"recorded {EXPECTED_FILE.relative_to(REPO)} ({doc['recorded']['reason']})")
