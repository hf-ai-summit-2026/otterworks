"""Purge audit (mig.purge_audit) and run reconciliation (failures, mig.run_sessions)."""

from __future__ import annotations

from collections.abc import Sequence

from ..base import FailureRow, PurgeAuditRow
from .connection import AzureSqlConnection


class PurgeAudit:
    def __init__(self, db: AzureSqlConnection):
        self._db = db

    def insert_purge_audit(self, run_id: str, namespace: str, table: str, keys: Sequence[str], batch_no: int) -> None:
        self._db.executemany(
            "IF NOT EXISTS (SELECT 1 FROM mig.purge_audit WHERE run_id = ? AND namespace = ? AND table_name = ? "
            "AND source_key = ?) INSERT mig.purge_audit (run_id, namespace, table_name, source_key, batch_no, status, "
            "intended_at) VALUES (?, ?, ?, ?, ?, N'INTENDED', SYSUTCDATETIME())",
            [(run_id, namespace, table, k, run_id, namespace, table, k, batch_no) for k in keys],
        )

    def set_purge_audit_status(self, run_id: str, namespace: str, table: str, keys: Sequence[str], status: str) -> None:
        self._db.executemany(
            "UPDATE mig.purge_audit SET status = ?, purged_at = CASE WHEN ? = N'PURGED' THEN SYSUTCDATETIME() END "
            "WHERE run_id = ? AND namespace = ? AND table_name = ? AND source_key = ?",
            [(status, status, run_id, namespace, table, k) for k in keys],
        )

    def purged_keys(self, run_id: str, namespace: str, table: str) -> set[str]:
        return {
            str(r[0])
            for r in self._db.rows(
                "SELECT source_key FROM mig.purge_audit WHERE run_id = ? AND namespace = ? AND table_name = ? "
                "AND status = N'PURGED'",
                (run_id, namespace, table),
            )
        }

    def purge_audit_rows(self, run_id: str, namespace: str, table: str) -> list[PurgeAuditRow]:
        return [
            PurgeAuditRow(table, str(k), int(b), str(s))  # type: ignore[call-overload]
            for k, b, s in self._db.rows(
                "SELECT source_key, batch_no, status FROM mig.purge_audit WHERE run_id = ? AND namespace = ? "
                "AND table_name = ? ORDER BY batch_no, source_key",
                (run_id, namespace, table),
            )
        ]


class Reconciliation:
    def __init__(self, db: AzureSqlConnection):
        self._db = db

    def failures(self, run_id: str, namespace: str) -> list[FailureRow]:
        sql = (
            "SELECT table_name, source_key, stage, rule_name, field, sqlstate, native_error, error "
            "FROM mig.v_reconciliation_failures WHERE run_id = ? AND namespace = ? "
            "UNION ALL "
            "SELECT v.table_name, v.source_key, N'VALIDATE', ISNULL(v.rule_name, N''), NULL, NULL, NULL, N'' "
            "FROM mig.validation v WHERE v.run_id = ? AND v.namespace = ? AND v.status = N'FAILED' "
            "AND NOT EXISTS (SELECT 1 FROM mig.rejects j WHERE j.run_id = v.run_id AND j.namespace = v.namespace "
            "AND j.table_name = v.table_name AND j.source_key = v.source_key) "
            "ORDER BY 1, 2"
        )
        return [
            FailureRow(
                str(t),
                str(k),
                str(st),
                str(rule),
                str(f) if f is not None else None,
                str(ss) if ss is not None else None,
                int(ne) if ne is not None else None,  # type: ignore[call-overload]
                str(err),
            )
            for t, k, st, rule, f, ss, ne, err in self._db.rows(sql, (run_id, namespace, run_id, namespace))
        ]

    def insert_run_sessions(self, run_id: str, namespace: str, sessions: Sequence[tuple[str, str]]) -> None:
        self._db.execute("DELETE FROM mig.run_sessions WHERE run_id = ? AND namespace = ?", (run_id, namespace)).close()  # type: ignore[attr-defined]
        self._db.executemany(
            "INSERT mig.run_sessions (run_id, namespace, ordinal, label, url) VALUES (?, ?, ?, ?, ?)",
            [(run_id, namespace, i + 1, label[:128], url[:512]) for i, (label, url) in enumerate(sessions)],
        )
