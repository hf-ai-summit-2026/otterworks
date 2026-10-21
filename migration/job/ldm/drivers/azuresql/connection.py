"""pyodbc connection lifecycle and the cursor helpers every collaborator executes through.

Every ODBC error surfaces as TargetError(sqlstate, native_error, text).
"""

from __future__ import annotations

from collections.abc import Sequence
from types import ModuleType

from ...errors import ConfigError, TargetError
from ._sql import parse_odbc_error, split_batches


class AzureSqlConnection:
    def __init__(
        self,
        server: str,
        database: str,
        auth: str,
        user: str | None,
        password: str | None,
        client_id: str | None,
        *,
        driver: str = "ODBC Driver 18 for SQL Server",
    ):
        self.server, self.database, self.auth = server, database, auth
        self.user, self.password, self.client_id = user, password, client_id
        self.driver = driver
        self._pyodbc: ModuleType | None = None
        self._conn: object | None = None

    @property
    def pyodbc(self) -> ModuleType:
        if self._pyodbc is None:
            try:
                import pyodbc
            except ImportError as e:  # pragma: no cover - exercised only in the image
                raise ConfigError("pyodbc is not installed; pip install 'ldm[azuresql]'") from e
            self._pyodbc = pyodbc
        return self._pyodbc

    def connection_string(self) -> str:
        server = self.server if "," in self.server or ":" in self.server else f"tcp:{self.server},1433"
        base = (
            f"Driver={{{self.driver}}};Server={server};Database={self.database};Encrypt=yes;TrustServerCertificate=no;"
        )
        if self.auth == "sql":
            return base + f"UID={self.user};PWD={self.password};"
        if self.auth == "managed-identity":
            mi = "Authentication=ActiveDirectoryMsi;"
            return base + mi + (f"UID={self.client_id};" if self.client_id else "")
        raise ConfigError(f"unknown target auth {self.auth!r}")

    def connect(self) -> None:
        if self._conn is not None:
            return
        try:
            self._conn = self.pyodbc.connect(self.connection_string(), autocommit=True, timeout=30)
        except self.pyodbc.Error as e:
            raise TargetError(*parse_odbc_error(e)) from e

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()  # type: ignore[attr-defined]
            self._conn = None

    @property
    def conn(self) -> object:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        return self._conn

    def cursor(self) -> object:
        return self.conn.cursor()  # type: ignore[attr-defined]

    def execute(self, sql: str, params: Sequence[object] = ()) -> object:
        try:
            cur = self.cursor()
            cur.execute(sql, *params)  # type: ignore[attr-defined]
            return cur
        except self.pyodbc.Error as e:
            raise TargetError(*parse_odbc_error(e)) from e

    def rows(self, sql: str, params: Sequence[object] = ()) -> list[tuple[object, ...]]:
        cur = self.execute(sql, params)
        try:
            return [tuple(r) for r in cur.fetchall()]  # type: ignore[attr-defined]
        finally:
            cur.close()  # type: ignore[attr-defined]

    def scalar(self, sql: str, params: Sequence[object] = ()) -> object:
        rows = self.rows(sql, params)
        return rows[0][0] if rows else None

    def executemany(self, sql: str, rows: Sequence[Sequence[object]]) -> None:
        if not rows:
            return
        # Under autocommit every element of the parameter array is its own commit (one WRITELOG wait per
        # row), so a batch runs as one transaction unless the caller already opened one.
        conn = self.conn
        own_txn = bool(conn.autocommit)  # type: ignore[attr-defined]
        try:
            if own_txn:
                conn.autocommit = False  # type: ignore[attr-defined]
            cur = self.cursor()
            cur.fast_executemany = True  # type: ignore[attr-defined]
            cur.executemany(sql, [list(r) for r in rows])  # type: ignore[attr-defined]
            cur.close()  # type: ignore[attr-defined]
            if own_txn:
                conn.commit()  # type: ignore[attr-defined]
        except self.pyodbc.Error as e:
            if own_txn:
                conn.rollback()  # type: ignore[attr-defined]
            raise TargetError(*parse_odbc_error(e)) from e
        finally:
            if own_txn:
                conn.autocommit = True  # type: ignore[attr-defined]

    def script(self, sql_text: str, cur: object | None = None) -> None:
        own = cur is None
        c = cur if cur is not None else self.cursor()
        try:
            for batch in split_batches(sql_text):
                c.execute(batch)  # type: ignore[attr-defined]
                while c.nextset():  # type: ignore[attr-defined]
                    pass
        except self.pyodbc.Error as e:
            raise TargetError(*parse_odbc_error(e)) from e
        finally:
            if own:
                c.close()  # type: ignore[attr-defined]
