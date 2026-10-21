"""Incident-responder harness for document-service.

    incident.py arm <scenario>          plant the flaw, seed, start load
    incident.py disarm                  reverse whatever is armed, stop load
    incident.py status                  firing alerts + the numbers behind them
    incident.py verify <scenario> --expect before|after
                                        fail-closed gate: fixture fingerprint,
                                        alert state, before/after thresholds
    incident.py load <scenario> [--duration S]   run the scenario's load in the foreground
    incident.py seed                    idempotent deterministic dataset
    incident.py simulate-alert          print what the Devin webhook / Slack received
    incident.py fingerprint             print the fixture + source fingerprints
    incident.py record --reason "..."   re-pin incident/expected.yaml (audited)

Every command reads incident/scenarios.yaml; targets are overridable with
INCIDENT_BASE_URL, INCIDENT_PROM_URL, INCIDENT_ALERTMANAGER_URL,
INCIDENT_SINK_URL, INCIDENT_REDIS_URL. INCIDENT_LOAD_SCALE (default 1) scales a
scenario's rps and concurrency for `arm` and `load` against targets with less
headroom than the local stack (a single-replica tenant on the shared cluster
runs one 500m-CPU worker); `verify` ignores it and always soaks at the catalog's
pinned profile, so a gate never passes under a lighter load than it recorded.
`verify` always writes a report to incident/reports/ (pass or fail) so a red
gate leaves evidence behind.
"""

from __future__ import annotations

import argparse
import asyncio

from .compose import reset_fixture
from .config import DEFAULT_SOAK_SECONDS, load_catalog, load_scale
from .fingerprint import cmd_fingerprint, cmd_record
from .load import _drive, stop_background_load
from .scenarios import cmd_arm, cmd_disarm
from .seed import seed
from .verify import cmd_simulate_alert, cmd_status, cmd_verify


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="incident.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("arm")
    p.add_argument("scenario")
    p.set_defaults(fn=cmd_arm)

    sub.add_parser("disarm").set_defaults(fn=cmd_disarm)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("fingerprint").set_defaults(fn=cmd_fingerprint)
    sub.add_parser("seed").set_defaults(fn=lambda _: asyncio.run(seed(load_catalog())))
    sub.add_parser("reset-fixture").set_defaults(fn=lambda _: reset_fixture(load_catalog()))
    sub.add_parser("stop-load").set_defaults(fn=lambda _: stop_background_load())

    p = sub.add_parser("load")
    p.add_argument("scenario")
    p.add_argument(
        "--duration", type=float, default=None, help="seconds; default runs until SIGTERM"
    )
    p.set_defaults(
        fn=lambda a: asyncio.run(_drive(load_catalog(), a.scenario, a.duration, load_scale()))
    )

    p = sub.add_parser("verify")
    p.add_argument("scenario")
    p.add_argument("--expect", choices=["before", "after"], required=True)
    p.add_argument(
        "--soak",
        type=float,
        default=None,
        help=(
            "seconds of load before judging the after-state (default: the scenario's "
            f"after_soak_seconds, else {DEFAULT_SOAK_SECONDS})"
        ),
    )
    p.add_argument(
        "--keep-going",
        action="store_true",
        help="continue past fingerprint failures (diagnostics only)",
    )
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("simulate-alert")
    p.add_argument("--receiver", choices=["devin", "slack", "sink"], default="devin")
    p.set_defaults(fn=cmd_simulate_alert)

    p = sub.add_parser("record")
    p.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_record)

    args = ap.parse_args()
    args.fn(args)
