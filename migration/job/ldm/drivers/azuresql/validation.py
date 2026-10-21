"""mig.validation / mig.class_totals bookkeeping and promotion of validated rows into arch.<table>."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from ..base import ClassTotalRow, ValidationRow
from ._sql import _ident, bind_value
from .connection import AzureSqlConnection
from .shapes import ShapeRegistry


class ValidationStore:
    def __init__(self, db: AzureSqlConnection, shapes: ShapeRegistry):
        self._db = db
        self._shapes = shapes

    def write_validation(self, run_id: str, namespace: str, rows: Sequence[ValidationRow]) -> None:
        if not rows:
            return
        self._db.executemany(
            "DELETE FROM mig.validation WHERE run_id = ? AND namespace = ? AND table_name = ? AND source_key = ?",
            [(run_id, namespace, r.table_name, r.source_key) for r in rows],
        )
        self._db.executemany(
            "INSERT mig.validation (run_id, namespace, table_name, source_key, source_hash, target_hash, status, "
            "rule_name, purge_safe) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    run_id,
                    namespace,
                    r.table_name,
                    r.source_key,
                    r.source_hash if r.source_hash is not None else bytes(32),
                    r.target_hash,
                    r.status,
                    r.rule,
                    r.purge_safe,
                )
                for r in rows
            ],
        )
        self._db.executemany(
            f"UPDATE s SET row_hash = ? FROM stg.{_ident(rows[0].table_name)} s "
            "WHERE s.run_id = ? AND s.namespace = ? AND s.source_key = ?",
            [(r.source_hash, run_id, namespace, r.source_key) for r in rows if r.source_hash is not None],
        )

    def write_class_totals(self, run_id: str, namespace: str, rows: Sequence[ClassTotalRow]) -> None:
        for table in {r.table_name for r in rows}:
            self._db.execute(
                "DELETE FROM mig.class_totals WHERE run_id = ? AND namespace = ? AND table_name = ?",
                (run_id, namespace, table),
            ).close()  # type: ignore[attr-defined]
        params: list[tuple[object, ...]] = []
        for r in rows:
            params.append(
                (run_id, namespace, r.table_name, r.retention_class, "SOURCE", r.source_count, bind_value(r.source_sum))
            )
            params.append(
                (run_id, namespace, r.table_name, r.retention_class, "TARGET", r.target_count, bind_value(r.target_sum))
            )
        self._db.executemany(
            "INSERT mig.class_totals (run_id, namespace, table_name, class_code, side, row_count, charge_sum) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            params,
        )

    def get_class_totals(self, run_id: str, namespace: str) -> list[ClassTotalRow]:
        sql = (
            "SELECT s.table_name, s.class_code, s.row_count, t.row_count, s.charge_sum, t.charge_sum "
            "FROM mig.class_totals s JOIN mig.class_totals t ON t.run_id = s.run_id AND t.namespace = s.namespace "
            "AND t.table_name = s.table_name AND t.class_code = s.class_code AND t.side = N'TARGET' "
            "WHERE s.run_id = ? AND s.namespace = ? AND s.side = N'SOURCE' ORDER BY s.table_name, s.class_code"
        )
        out: list[ClassTotalRow] = []
        for tn, cls, sc, tc, ss, tsum in self._db.rows(sql, (run_id, namespace)):
            s_sum = Decimal(str(ss)) if ss is not None else None
            t_sum = Decimal(str(tsum)) if tsum is not None else None
            status = "MATCH" if sc == tc and s_sum == t_sum else "MISMATCH"
            out.append(ClassTotalRow(str(tn), str(cls), int(sc), int(tc), s_sum, t_sum, status))  # type: ignore[call-overload]
        return out

    def archived_hashes(self, run_id: str, namespace: str, table: str, key_columns: Sequence[str]) -> dict[str, bytes]:
        key_match = " AND ".join(f"a.{_ident(k)} = s.{_ident(k)}" for k in key_columns)
        rows = self._db.rows(
            f"SELECT s.source_key, a.row_hash FROM stg.{_ident(table)} s JOIN arch.{_ident(table)} a "
            f"ON a.namespace = s.namespace AND {key_match} WHERE s.run_id = ? AND s.namespace = ?",
            (run_id, namespace),
        )
        return {str(k): bytes(h) for k, h in rows}  # type: ignore[call-overload]

    def promote(self, run_id: str, namespace: str, table: str, key_columns: Sequence[str]) -> int:
        columns = self._shapes.get(table).target_columns
        cols = ", ".join(_ident(c) for c in columns)
        key_match = " AND ".join(f"a.{_ident(k)} = s.{_ident(k)}" for k in key_columns)
        cur = self._db.execute(
            f"INSERT arch.{_ident(table)} ({cols}, source_key, row_hash, namespace, migrated_run_id) "
            f"SELECT {', '.join('s.' + _ident(c) for c in columns)}, s.source_key, s.row_hash, s.namespace, s.run_id "
            f"FROM stg.{_ident(table)} s JOIN mig.validation v ON v.run_id = s.run_id AND v.namespace = s.namespace "
            "AND v.table_name = ? AND v.source_key = s.source_key AND v.status = N'VALIDATED' "
            f"WHERE s.run_id = ? AND s.namespace = ? "
            f"AND NOT EXISTS (SELECT 1 FROM arch.{_ident(table)} a WHERE a.namespace = s.namespace AND {key_match})",
            (table, run_id, namespace),
        )
        n = int(cur.rowcount)  # type: ignore[attr-defined]
        cur.close()  # type: ignore[attr-defined]
        return max(n, 0)

    def purge_safe_keys(self, run_id: str, namespace: str, table: str) -> list[str]:
        return [
            str(r[0])
            for r in self._db.rows(
                "SELECT source_key FROM mig.validation WHERE run_id = ? AND namespace = ? AND table_name = ? "
                "AND purge_safe = 1 ORDER BY source_key",
                (run_id, namespace, table),
            )
        ]

    def count_validation(self, run_id: str, namespace: str, table: str, status: str) -> int:
        v = self._db.scalar(
            "SELECT COUNT(*) FROM mig.validation WHERE run_id = ? AND namespace = ? AND table_name = ? AND status = ?",
            (run_id, namespace, table, status),
        )
        return int(v)  # type: ignore[call-overload]
