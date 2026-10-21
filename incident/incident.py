#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx==0.27.2", "pyyaml==6.0.2", "PyJWT==2.9.0", "redis==5.2.1"]
# ///
"""Incident-responder harness for document-service: entry point.

The CLI contract is documented in harness/cli.py (`incident.py --help`); the
implementation lives in the harness/ package next to this file.
"""

from harness.cli import main

if __name__ == "__main__":
    main()
