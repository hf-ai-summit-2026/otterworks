"""Azure SQL target driver over pyodbc + msodbcsql18 (CONTRACTS.md §6, §9).

The target hosts mig.* (ledger, rejects, validation, purge audit), stg.* (staging) and arch.* (served rows).
AzureSqlTarget is a thin TargetDriver facade; each labeled concern lives in its own collaborator module, all
executing through one AzureSqlConnection. Every ODBC error surfaces as TargetError(sqlstate, native_error, text);
batch inserts fall back to row-by-row so one bad row never loses its batch (§9.4.2).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from ...typemap import ColumnSpec
from ..base import (
    ClassAggregate,
    ClassTotalRow,
    FailureRow,
    InsertFailure,
    KeyRange,
    LedgerRow,
    PurgeAuditRow,
    Reject,
    StagedRow,
    ValidationRow,
)
from ._sql import (
    _IDENT_RE,
    KEY_RANGE_COLUMNS,
    LEDGER_COLUMNS,
    META_COLUMNS,
    _ident,
    bind_value,
    parse_odbc_error,
    split_batches,
)
from .connection import AzureSqlConnection
from .key_ranges import KeyRangeStore
from .ledger import RunLedger
from .purge import PurgeAudit, Reconciliation
from .schema import SchemaApplier
from .shapes import ShapeRegistry
from .staging import StagingStore
from .validation import ValidationStore

__all__ = [
    "_IDENT_RE",
    "KEY_RANGE_COLUMNS",
    "LEDGER_COLUMNS",
    "META_COLUMNS",
    "AzureSqlConnection",
    "AzureSqlTarget",
    "_ident",
    "bind_value",
    "parse_odbc_error",
    "split_batches",
]


class AzureSqlTarget:
    """TargetDriver for Azure SQL Database / SQL Server 2022 (msodbcsql18)."""

    def __init__(
        self,
        server: str,
        database: str,
        auth: str,
        user: str | None,
        password: str | None,
        client_id: str | None,
        *,
        host: str = "local",
        driver: str = "ODBC Driver 18 for SQL Server",
    ):
        self.host = host
        self.shapes = ShapeRegistry()
        self._connection = AzureSqlConnection(server, database, auth, user, password, client_id, driver=driver)
        self._schema = SchemaApplier(self._connection)
        self._ledger = RunLedger(self._connection, host)
        self._key_ranges = KeyRangeStore(self._connection)
        self._staging = StagingStore(self._connection, self.shapes)
        self._validation = ValidationStore(self._connection, self.shapes)
        self._purge = PurgeAudit(self._connection)
        self._reconciliation = Reconciliation(self._connection)

    @property
    def connection(self) -> AzureSqlConnection:
        return self._connection

    # --- connection ---------------------------------------------------------------------------------------------------

    def connect(self) -> None:
        self._connection.connect()

    def close(self) -> None:
        self._connection.close()

    def register_table(
        self, table: str, key_columns: Sequence[str], hash_columns: Sequence[str], specs: list[ColumnSpec]
    ) -> None:
        self.shapes.register(table, key_columns, hash_columns, specs)

    # --- init ---------------------------------------------------------------------------------------------------------

    def applied_ddl(self) -> dict[str, str]:
        return self._schema.applied_ddl()

    def apply_ddl(self, sql_text: str, file_name: str, sha256_hex: str) -> None:
        self._schema.apply_ddl(sql_text, file_name, sha256_hex)

    def ensure_reader(self, user: str, password: str) -> None:
        self._schema.ensure_reader(user, password)

    def apply_sql_in_namespace(self, sql_text: str, namespace: str) -> None:
        self._schema.apply_sql_in_namespace(sql_text, namespace)

    # --- run / ledger / stage log -------------------------------------------------------------------------------------

    def ensure_run(
        self, run_id: str, namespace: str, purge_enabled: bool, job_image: str | None, manifest_sha: str
    ) -> str:
        return self._ledger.ensure_run(run_id, namespace, purge_enabled, job_image, manifest_sha)

    def refresh_run(self, run_id: str, namespace: str, purge_enabled: bool, job_image: str | None) -> None:
        self._ledger.refresh_run(run_id, namespace, purge_enabled, job_image)

    def get_run_status(self, run_id: str, namespace: str) -> str | None:
        return self._ledger.get_run_status(run_id, namespace)

    def set_run_status(self, run_id: str, namespace: str, status: str, exit_code: int | None) -> None:
        self._ledger.set_run_status(run_id, namespace, status, exit_code)

    def ensure_ledger(self, run_id: str, namespace: str, tables: Sequence[tuple[str, int, str]]) -> None:
        self._ledger.ensure_ledger(run_id, namespace, tables)

    def get_ledger(self, run_id: str, namespace: str) -> dict[str, LedgerRow]:
        return self._ledger.get_ledger(run_id, namespace)

    def update_ledger(self, run_id: str, namespace: str, table: str, **cols: int | bool | None) -> None:
        self._ledger.update_ledger(run_id, namespace, table, **cols)

    def stage_log_start(self, run_id: str, namespace: str, stage: str, table: str | None) -> int:
        return self._ledger.stage_log_start(run_id, namespace, stage, table)

    def stage_log_finish(self, log_id: int, status: str, rows: int | None, message: str | None) -> None:
        self._ledger.stage_log_finish(log_id, status, rows, message)

    # --- key ranges ---------------------------------------------------------------------------------------------------

    def get_key_ranges(self, run_id: str, namespace: str, table: str) -> list[KeyRange]:
        return self._key_ranges.get_key_ranges(run_id, namespace, table)

    def insert_key_ranges(self, run_id: str, namespace: str, ranges: Sequence[KeyRange]) -> None:
        self._key_ranges.insert_key_ranges(run_id, namespace, ranges)

    def update_key_range(self, run_id: str, namespace: str, table: str, range_seq: int, **cols: object) -> None:
        self._key_ranges.update_key_range(run_id, namespace, table, range_seq, **cols)

    # --- rejects / staging --------------------------------------------------------------------------------------------

    def insert_rejects(self, run_id: str, namespace: str, rejects: Sequence[Reject]) -> None:
        self._staging.insert_rejects(run_id, namespace, rejects)

    def count_rejects(self, run_id: str, namespace: str, table: str, stage: str | None = None) -> int:
        return self._staging.count_rejects(run_id, namespace, table, stage)

    def delete_rejects_keys(self, run_id: str, namespace: str, table: str, stage: str, keys: Sequence[str]) -> None:
        self._staging.delete_rejects_keys(run_id, namespace, table, stage, keys)

    def delete_rejects_range(self, run_id: str, namespace: str, table: str, stage: str, range_seq: int) -> None:
        self._staging.delete_rejects_range(run_id, namespace, table, stage, range_seq)

    def delete_staging_range(self, run_id: str, namespace: str, table: str, range_seq: int) -> None:
        self._staging.delete_staging_range(run_id, namespace, table, range_seq)

    def insert_staging(self, run_id: str, namespace: str, table: str, rows: Sequence[StagedRow]) -> list[InsertFailure]:
        return self._staging.insert_staging(run_id, namespace, table, rows)

    def count_staging(self, run_id: str, namespace: str, table: str) -> int:
        return self._staging.count_staging(run_id, namespace, table)

    def iter_staging(self, run_id: str, namespace: str, table: str, batch: int) -> Iterator[list[StagedRow]]:
        return self._staging.iter_staging(run_id, namespace, table, batch)

    def target_hashes(
        self, run_id: str, namespace: str, table: str, tsql_expr: str, key_from: str, key_to: str
    ) -> dict[str, bytes]:
        return self._staging.target_hashes(run_id, namespace, table, tsql_expr, key_from, key_to)

    def class_aggregates(
        self, run_id: str, namespace: str, table: str, class_column: str, sum_columns: Sequence[str]
    ) -> dict[str, ClassAggregate]:
        return self._staging.class_aggregates(run_id, namespace, table, class_column, sum_columns)

    def parents_present(
        self,
        run_id: str,
        namespace: str,
        child_table: str,
        child_columns: Sequence[str],
        parent_table: str,
        parent_columns: Sequence[str],
    ) -> set[str]:
        return self._staging.parents_present(
            run_id, namespace, child_table, child_columns, parent_table, parent_columns
        )

    def delete_staging_run(self, run_id: str, namespace: str) -> None:
        self._staging.delete_staging_run(run_id, namespace)

    # --- validation ---------------------------------------------------------------------------------------------------

    def write_validation(self, run_id: str, namespace: str, rows: Sequence[ValidationRow]) -> None:
        self._validation.write_validation(run_id, namespace, rows)

    def write_class_totals(self, run_id: str, namespace: str, rows: Sequence[ClassTotalRow]) -> None:
        self._validation.write_class_totals(run_id, namespace, rows)

    def get_class_totals(self, run_id: str, namespace: str) -> list[ClassTotalRow]:
        return self._validation.get_class_totals(run_id, namespace)

    def archived_hashes(self, run_id: str, namespace: str, table: str, key_columns: Sequence[str]) -> dict[str, bytes]:
        return self._validation.archived_hashes(run_id, namespace, table, key_columns)

    def promote(self, run_id: str, namespace: str, table: str, key_columns: Sequence[str]) -> int:
        return self._validation.promote(run_id, namespace, table, key_columns)

    def purge_safe_keys(self, run_id: str, namespace: str, table: str) -> list[str]:
        return self._validation.purge_safe_keys(run_id, namespace, table)

    def count_validation(self, run_id: str, namespace: str, table: str, status: str) -> int:
        return self._validation.count_validation(run_id, namespace, table, status)

    # --- purge audit --------------------------------------------------------------------------------------------------

    def insert_purge_audit(self, run_id: str, namespace: str, table: str, keys: Sequence[str], batch_no: int) -> None:
        self._purge.insert_purge_audit(run_id, namespace, table, keys, batch_no)

    def set_purge_audit_status(self, run_id: str, namespace: str, table: str, keys: Sequence[str], status: str) -> None:
        self._purge.set_purge_audit_status(run_id, namespace, table, keys, status)

    def purged_keys(self, run_id: str, namespace: str, table: str) -> set[str]:
        return self._purge.purged_keys(run_id, namespace, table)

    def purge_audit_rows(self, run_id: str, namespace: str, table: str) -> list[PurgeAuditRow]:
        return self._purge.purge_audit_rows(run_id, namespace, table)

    # --- reconcile ----------------------------------------------------------------------------------------------------

    def failures(self, run_id: str, namespace: str) -> list[FailureRow]:
        return self._reconciliation.failures(run_id, namespace)

    def insert_run_sessions(self, run_id: str, namespace: str, sessions: Sequence[tuple[str, str]]) -> None:
        self._reconciliation.insert_run_sessions(run_id, namespace, sessions)
