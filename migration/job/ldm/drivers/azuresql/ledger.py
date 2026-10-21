"""Run, run-ledger and stage-log bookkeeping (mig.runs, mig.run_ledger, mig.stage_log)."""

from __future__ import annotations

from collections.abc import Sequence

from ..base import LedgerRow
from ._sql import LEDGER_COLUMNS, _ident
from .connection import AzureSqlConnection


class RunLedger:
    def __init__(self, db: AzureSqlConnection, host: str):
        self._db = db
        self._host = host

    def ensure_run(
        self, run_id: str, namespace: str, purge_enabled: bool, job_image: str | None, manifest_sha: str
    ) -> str:
        existing = self._db.scalar(
            "SELECT manifest_sha256 FROM mig.runs WHERE run_id = ? AND namespace = ?", (run_id, namespace)
        )
        if existing is None:
            self._db.exec_sql(
                "INSERT mig.runs (run_id, namespace, status, purge_enabled, manifest_sha256, job_image) "
                "VALUES (?, ?, N'RUNNING', ?, ?, ?)",
                (run_id, namespace, purge_enabled, manifest_sha, job_image),
            ).close()  # type: ignore[attr-defined]
            return manifest_sha
        return str(existing).strip()

    def refresh_run(self, run_id: str, namespace: str, purge_enabled: bool, job_image: str | None) -> None:
        self._db.exec_sql(
            "UPDATE mig.runs SET purge_enabled = ?, job_image = COALESCE(?, job_image) "
            "WHERE run_id = ? AND namespace = ?",
            (purge_enabled, job_image, run_id, namespace),
        ).close()  # type: ignore[attr-defined]

    def get_run_status(self, run_id: str, namespace: str) -> str | None:
        v = self._db.scalar("SELECT status FROM mig.runs WHERE run_id = ? AND namespace = ?", (run_id, namespace))
        return str(v) if v is not None else None

    def set_run_status(self, run_id: str, namespace: str, status: str, exit_code: int | None) -> None:
        closes = None if status == "RUNNING" else status == "CLOSED"
        self._db.exec_sql(
            "UPDATE mig.runs SET status = ?, exit_code = ?, closes = ?, "
            "finished_at = CASE WHEN ? = N'RUNNING' THEN NULL ELSE SYSUTCDATETIME() END "
            "WHERE run_id = ? AND namespace = ?",
            (status, exit_code, closes, status, run_id, namespace),
        ).close()  # type: ignore[attr-defined]

    def ensure_ledger(self, run_id: str, namespace: str, tables: Sequence[tuple[str, int, str]]) -> None:
        for name, order, role in tables:
            self._db.exec_sql(
                "IF NOT EXISTS (SELECT 1 FROM mig.run_ledger WHERE run_id = ? AND namespace = ? AND table_name = ?) "
                "INSERT mig.run_ledger (run_id, namespace, table_name, table_order, table_role) VALUES (?, ?, ?, ?, ?)",
                (run_id, namespace, name, run_id, namespace, name, order, role),
            ).close()  # type: ignore[attr-defined]

    def get_ledger(self, run_id: str, namespace: str) -> dict[str, LedgerRow]:
        cols = (
            "table_name, table_order, table_role, extracted, extract_files, loaded, rejected, validated, "
            "validate_failed, purge_intended, purged, purge_dry_run"
        )
        out: dict[str, LedgerRow] = {}
        for r in self._db.rows(
            f"SELECT {cols} FROM mig.run_ledger WHERE run_id = ? AND namespace = ?", (run_id, namespace)
        ):
            name = str(r[0])
            ints = [int(v) if v is not None else None for v in r[3:11]]
            out[name] = LedgerRow(
                name, int(r[1]), str(r[2]), *ints, purge_dry_run=bool(r[11]) if r[11] is not None else None
            )
        return out

    def update_ledger(self, run_id: str, namespace: str, table: str, **cols: int | bool | None) -> None:
        unknown = set(cols) - LEDGER_COLUMNS
        if unknown:
            raise KeyError(f"unknown ledger columns {sorted(unknown)}")
        if not cols:
            return
        sets = ", ".join(f"{_ident(c)} = ?" for c in cols) + ", updated_at = SYSUTCDATETIME()"
        self._db.exec_sql(
            f"UPDATE mig.run_ledger SET {sets} WHERE run_id = ? AND namespace = ? AND table_name = ?",
            (*cols.values(), run_id, namespace, table),
        ).close()  # type: ignore[attr-defined]

    def stage_log_start(self, run_id: str, namespace: str, stage: str, table: str | None) -> int:
        attempt = self._db.scalar(
            "SELECT COUNT(*) + 1 FROM mig.stage_log WHERE run_id = ? AND namespace = ? AND stage = ? "
            "AND ISNULL(table_name, N'') = ISNULL(?, N'')",
            (run_id, namespace, stage, table),
        )
        v = self._db.scalar(
            "INSERT mig.stage_log (run_id, namespace, stage, table_name, host, attempt, status, started_at) "
            "OUTPUT INSERTED.stage_log_id VALUES (?, ?, ?, ?, ?, ?, N'RUNNING', SYSUTCDATETIME())",
            (run_id, namespace, stage, table, self._host, attempt),
        )
        assert v is not None
        return int(v)  # type: ignore[call-overload]

    def stage_log_finish(self, log_id: int, status: str, rows: int | None, message: str | None) -> None:
        self._db.exec_sql(
            "UPDATE mig.stage_log SET status = ?, rows_processed = ?, message = ?, finished_at = SYSUTCDATETIME() "
            "WHERE stage_log_id = ?",
            (status, rows, message, log_id),
        ).close()  # type: ignore[attr-defined]
