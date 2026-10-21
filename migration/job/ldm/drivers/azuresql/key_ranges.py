"""Extract/load restart bookkeeping in mig.key_ranges."""

from __future__ import annotations

from collections.abc import Sequence

from ..base import KeyRange
from ._sql import KEY_RANGE_COLUMNS, _ident
from .connection import AzureSqlConnection


class KeyRangeStore:
    def __init__(self, db: AzureSqlConnection):
        self._db = db

    def get_key_ranges(self, run_id: str, namespace: str, table: str) -> list[KeyRange]:
        sql = (
            "SELECT range_seq, key_from, key_to, extract_status, rows_extracted, file_bytes, file_sha256, file_name, "
            "load_status FROM mig.key_ranges WHERE run_id = ? AND namespace = ? AND table_name = ? ORDER BY range_seq"
        )
        return [
            KeyRange(
                table_name=table,
                range_seq=int(r[0]),  # type: ignore[call-overload]
                key_from=str(r[1]),
                key_to=str(r[2]),
                status=str(r[3]),
                row_count=int(r[4]) if r[4] is not None else None,  # type: ignore[call-overload]
                byte_count=int(r[5]) if r[5] is not None else None,  # type: ignore[call-overload]
                sha256_hex=str(r[6]).strip() if r[6] is not None else None,
                blob_path=str(r[7]) if r[7] is not None else None,
                load_status=str(r[8]),
            )
            for r in self._db.rows(sql, (run_id, namespace, table))
        ]

    def insert_key_ranges(self, run_id: str, namespace: str, ranges: Sequence[KeyRange]) -> None:
        self._db.executemany(
            "INSERT mig.key_ranges (run_id, namespace, table_name, range_seq, key_from, key_to, extract_status, "
            "load_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (run_id, namespace, r.table_name, r.range_seq, r.key_from, r.key_to, r.status, r.load_status)
                for r in ranges
            ],
        )

    def update_key_range(self, run_id: str, namespace: str, table: str, range_seq: int, **cols: object) -> None:
        unknown = set(cols) - set(KEY_RANGE_COLUMNS)
        if unknown:
            raise KeyError(f"unknown key_ranges columns {sorted(unknown)}")
        sets: list[str] = []
        params: list[object] = []
        for name, value in cols.items():
            col = KEY_RANGE_COLUMNS[name]
            if col is None:
                continue
            sets.append(f"{_ident(col)} = ?")
            params.append(value)
            if name == "status" and value == "DONE":
                sets.append("extracted_at = SYSUTCDATETIME()")
            if name == "load_status" and value == "DONE":
                sets.append("loaded_at = SYSUTCDATETIME()")
        if not sets:
            return
        self._db.execute(
            f"UPDATE mig.key_ranges SET {', '.join(sets)} "
            "WHERE run_id = ? AND namespace = ? AND table_name = ? AND range_seq = ?",
            (*params, run_id, namespace, table, range_seq),
        ).close()  # type: ignore[attr-defined]
