"""stg.<table> staging rows and mig.rejects; batch inserts bisect so one bad row never loses its batch."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date, datetime
from decimal import Decimal

from ...errors import TargetError
from ..base import ClassAggregate, InsertFailure, Reject, StagedRow, TargetValue
from ._sql import _ident, bind_value
from .connection import AzureSqlConnection
from .shapes import ShapeRegistry


class StagingStore:
    def __init__(self, db: AzureSqlConnection, shapes: ShapeRegistry):
        self._db = db
        self._shapes = shapes

    def insert_rejects(self, run_id: str, namespace: str, rejects: Sequence[Reject]) -> None:
        sql = (
            "IF NOT EXISTS (SELECT 1 FROM mig.rejects WHERE run_id = ? AND namespace = ? AND table_name = ? "
            "AND source_key = ?) INSERT mig.rejects (run_id, namespace, table_name, source_key, stage, rule_name, "
            "field, sqlstate, native_error, error, raw_bytes, field_bytes, range_seq) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        for r in rejects:
            self._db.exec_sql(
                sql,
                (
                    run_id,
                    namespace,
                    r.table_name,
                    r.source_key,
                    run_id,
                    namespace,
                    r.table_name,
                    r.source_key,
                    r.stage,
                    r.rule,
                    r.field_name,
                    r.sqlstate,
                    r.native_error,
                    r.error_text[:4000],
                    r.raw_bytes,
                    r.field_bytes[:8000] if r.field_bytes is not None else None,
                    r.key_range_seq,
                ),
            ).close()  # type: ignore[attr-defined]

    def count_rejects(self, run_id: str, namespace: str, table: str, stage: str | None = None) -> int:
        v = self._db.scalar(
            "SELECT COUNT(*) FROM mig.rejects WHERE run_id = ? AND namespace = ? AND table_name = ? "
            "AND (? IS NULL OR stage = ?)",
            (run_id, namespace, table, stage, stage),
        )
        return int(v)  # type: ignore[call-overload]

    def delete_rejects_keys(self, run_id: str, namespace: str, table: str, stage: str, keys: Sequence[str]) -> None:
        self._db.executemany(
            "DELETE FROM mig.rejects "
            "WHERE run_id = ? AND namespace = ? AND table_name = ? AND stage = ? AND source_key = ?",
            [(run_id, namespace, table, stage, k) for k in keys],
        )

    def delete_rejects_range(self, run_id: str, namespace: str, table: str, stage: str, range_seq: int) -> None:
        self._db.exec_sql(
            "DELETE FROM mig.rejects WHERE run_id = ? AND namespace = ? AND table_name = ? "
            "AND stage = ? AND range_seq = ?",
            (run_id, namespace, table, stage, range_seq),
        ).close()  # type: ignore[attr-defined]

    def delete_staging_range(self, run_id: str, namespace: str, table: str, range_seq: int) -> None:
        self._db.exec_sql(
            f"DELETE FROM stg.{_ident(table)} WHERE run_id = ? AND namespace = ? AND range_seq = ?",
            (run_id, namespace, range_seq),
        ).close()  # type: ignore[attr-defined]

    def _insert_sql(self, table: str, columns: Sequence[str]) -> str:
        cols = ["run_id", "namespace", "source_key", "range_seq", "batch_id", "raw_bytes", *columns]
        return (
            f"INSERT stg.{_ident(table)} ({', '.join(_ident(c) for c in cols)}) VALUES ({', '.join('?' for _ in cols)})"
        )

    def _staging_params(self, run_id: str, namespace: str, row: StagedRow, columns: Sequence[str]) -> list[object]:
        seq = row.key_range_seq if row.key_range_seq is not None else 0
        return [run_id, namespace, row.source_key, seq, 0, row.raw_bytes, *(bind_value(row.values[c]) for c in columns)]

    def insert_staging(self, run_id: str, namespace: str, table: str, rows: Sequence[StagedRow]) -> list[InsertFailure]:
        if not rows:
            return []
        columns = self._shapes.get(table).target_columns
        sql = self._insert_sql(table, columns)
        params = [self._staging_params(run_id, namespace, r, columns) for r in rows]
        failures: list[InsertFailure] = []
        self._insert_bisect(sql, list(rows), params, failures)
        return failures

    def _insert_bisect(
        self, sql: str, rows: list[StagedRow], params: list[list[object]], failures: list[InsertFailure]
    ) -> None:
        """Insert rows as one transaction; on failure split in half so only the bad rows fall to single inserts."""
        try:
            self._db.executemany(sql, params)
            return
        except TargetError as e:
            if len(rows) == 1:
                failures.append(InsertFailure(rows[0].source_key, e.sqlstate, e.native_error, e.text))
                return
        mid = len(rows) // 2
        self._insert_bisect(sql, rows[:mid], params[:mid], failures)
        self._insert_bisect(sql, rows[mid:], params[mid:], failures)

    def count_staging(self, run_id: str, namespace: str, table: str) -> int:
        v = self._db.scalar(
            f"SELECT COUNT(*) FROM stg.{_ident(table)} WHERE run_id = ? AND namespace = ?", (run_id, namespace)
        )
        return int(v)  # type: ignore[call-overload]

    def iter_staging(self, run_id: str, namespace: str, table: str, batch: int) -> Iterator[list[StagedRow]]:
        columns = self._shapes.get(table).target_columns
        select = ", ".join(["source_key", "range_seq", "raw_bytes", *(_ident(c) for c in columns)])
        last = ""
        while True:
            rows = self._db.rows(
                f"SELECT TOP ({int(batch)}) {select} FROM stg.{_ident(table)} "
                "WHERE run_id = ? AND namespace = ? AND source_key > ? ORDER BY source_key",
                (run_id, namespace, last),
            )
            if not rows:
                return
            out: list[StagedRow] = []
            for r in rows:
                values: dict[str, TargetValue] = {}
                for c, v in zip(columns, r[3:], strict=True):
                    values[c] = self._read_value(v)
                out.append(StagedRow(table, str(r[0]), int(r[1]), bytes(r[2]), values))  # type: ignore[call-overload]
            last = str(rows[-1][0])
            yield out

    @staticmethod
    def _read_value(v: object) -> TargetValue:
        if v is None or isinstance(v, str | int | Decimal | bytes | datetime | date):
            return v
        if isinstance(v, bytearray | memoryview):
            return bytes(v)
        if isinstance(v, bool):
            return int(v)
        return str(v)

    def target_hashes(
        self, run_id: str, namespace: str, table: str, tsql_expr: str, key_from: str, key_to: str
    ) -> dict[str, bytes]:
        rows = self._db.rows(
            f"SELECT source_key, {tsql_expr} FROM stg.{_ident(table)} WHERE run_id = ? AND namespace = ? "
            "AND source_key >= ? AND source_key <= ?",
            (run_id, namespace, key_from, key_to),
        )
        return {str(k): bytes(h) for k, h in rows}  # type: ignore[call-overload]

    def class_aggregates(
        self, run_id: str, namespace: str, table: str, class_column: str, sum_columns: Sequence[str]
    ) -> dict[str, ClassAggregate]:
        sums = ", ".join(f"SUM(CAST({_ident(c)} AS DECIMAL(38,8)))" for c in sum_columns)
        sql = (
            f"SELECT RTRIM({_ident(class_column)}), COUNT_BIG(*){', ' + sums if sums else ''} "
            f"FROM stg.{_ident(table)} WHERE run_id = ? AND namespace = ? GROUP BY RTRIM({_ident(class_column)})"
        )
        out: dict[str, ClassAggregate] = {}
        for r in self._db.rows(sql, (run_id, namespace)):
            agg = ClassAggregate(count=int(r[1]))  # type: ignore[call-overload]
            for c, v in zip(sum_columns, r[2:], strict=True):
                agg.sums[c] = Decimal(str(v)) if v is not None else Decimal(0)
            out[str(r[0])] = agg
        return out

    def parents_present(
        self,
        run_id: str,
        namespace: str,
        child_table: str,
        child_columns: Sequence[str],
        parent_table: str,
        parent_columns: Sequence[str],
    ) -> set[str]:
        join = " AND ".join(
            f"RTRIM(c.{_ident(cc)}) = RTRIM(p.{_ident(pc)})"
            for cc, pc in zip(child_columns, parent_columns, strict=True)
        )
        sql = (
            f"SELECT c.source_key FROM stg.{_ident(child_table)} c WHERE c.run_id = ? AND c.namespace = ? AND ("
            f"EXISTS (SELECT 1 FROM stg.{_ident(parent_table)} p JOIN mig.validation v "
            "ON v.run_id = p.run_id AND v.namespace = p.namespace AND v.table_name = ? AND v.source_key = p.source_key "
            f"AND v.status = N'VALIDATED' WHERE p.run_id = c.run_id AND p.namespace = c.namespace AND {join}) "
            f"OR EXISTS (SELECT 1 FROM arch.{_ident(parent_table)} p WHERE p.namespace = c.namespace AND {join}))"
        )
        return {str(r[0]) for r in self._db.rows(sql, (run_id, namespace, parent_table))}

    def delete_staging_run(self, run_id: str, namespace: str) -> None:
        for table in self._shapes.tables:
            self._db.exec_sql(
                f"DELETE FROM stg.{_ident(table)} WHERE run_id = ? AND namespace = ?", (run_id, namespace)
            ).close()  # type: ignore[attr-defined]
