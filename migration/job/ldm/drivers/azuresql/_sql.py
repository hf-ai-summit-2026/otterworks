"""SQL-safety primitives shared by the Azure SQL collaborators.

Identifiers reach SQL text only through _ident() (validated against _IDENT_RE and bracket-quoted); every value is
bound as a `?` parameter.
"""

from __future__ import annotations

import re
from decimal import Decimal

from ...convert import Timestamp12
from ...errors import ConfigError
from ..base import LedgerRow, TargetValue

_NATIVE_RE = re.compile(r"\((\d+)\) \(SQL[A-Za-z]+\)")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_GO_RE = re.compile(r"^\s*GO\s*(?:--.*)?$", re.IGNORECASE | re.MULTILINE)

LEDGER_COLUMNS = frozenset(LedgerRow.__dataclass_fields__) - {"table_name", "table_order", "table_role"}
KEY_RANGE_COLUMNS = {
    "status": "extract_status",
    "row_count": "rows_extracted",
    "byte_count": "file_bytes",
    "sha256_hex": "file_sha256",
    "blob_path": "file_name",
    "local_path": None,  # not persisted (pod-local path)
    "load_status": "load_status",
    "attempt": None,
    "error_text": None,
}
META_COLUMNS = ("run_id", "namespace", "source_key", "range_seq", "batch_id", "raw_bytes", "row_hash", "loaded_at")


def parse_odbc_error(exc: BaseException) -> tuple[str | None, int | None, str]:
    """(sqlstate, native error number, text) from a pyodbc.Error."""
    args = exc.args
    sqlstate = str(args[0]) if args and isinstance(args[0], str) and len(args[0]) == 5 else None
    text = str(args[1]) if len(args) > 1 else str(exc)
    m = _NATIVE_RE.search(text)
    return sqlstate, (int(m.group(1)) if m else None), text


def _ident(name: str) -> str:
    if not _IDENT_RE.match(name):
        raise ConfigError(f"unsafe SQL identifier {name!r}")
    return f"[{name}]"


def split_batches(sql_text: str) -> list[str]:
    """Split a T-SQL script on GO lines, dropping empty batches."""
    return [b.strip() for b in _GO_RE.split(sql_text) if b.strip()]


def bind_value(v: TargetValue) -> object:
    """pyodbc parameter for one target value. Decimals travel as text so DECIMAL(31,8) keeps every digit."""
    if isinstance(v, Timestamp12):
        return v.datetime2_literal
    if isinstance(v, Decimal):
        return format(v, "f")
    return v
