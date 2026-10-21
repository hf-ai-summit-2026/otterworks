"""DDL application and reader provisioning on the Azure SQL target (mig.schema_version)."""

from __future__ import annotations

from ...errors import ConfigError, TargetError
from ._sql import _IDENT_RE, _ident, parse_odbc_error
from .connection import AzureSqlConnection


class SchemaApplier:
    def __init__(self, db: AzureSqlConnection):
        self._db = db

    def applied_ddl(self) -> dict[str, str]:
        if self._db.scalar("SELECT OBJECT_ID(N'mig.schema_version', N'U')") is None:
            return {}
        return {
            str(f): str(s).strip() for f, s in self._db.rows("SELECT file_name, file_sha256 FROM mig.schema_version")
        }

    def apply_ddl(self, sql_text: str, file_name: str, sha256_hex: str) -> None:
        self._db.script(sql_text)
        self._db.exec_sql(
            "MERGE mig.schema_version AS t USING (SELECT ? AS file_name, ? AS file_sha256) AS s "
            "ON t.file_name = s.file_name "
            "WHEN MATCHED THEN UPDATE SET file_sha256 = s.file_sha256, applied_at = SYSUTCDATETIME() "
            "WHEN NOT MATCHED THEN INSERT (file_name, file_sha256) VALUES (s.file_name, s.file_sha256);",
            (file_name, sha256_hex),
        ).close()  # type: ignore[attr-defined]

    def ensure_reader(self, user: str, password: str) -> None:
        if not _IDENT_RE.match(user):
            raise ConfigError(f"unsafe reader user name {user!r}")
        pwd = password.replace("'", "''")
        self._db.script(
            f"IF DATABASE_PRINCIPAL_ID(N'{user}') IS NULL CREATE USER {_ident(user)} WITH PASSWORD = N'{pwd}';\n"
            f"ELSE ALTER USER {_ident(user)} WITH PASSWORD = N'{pwd}';\nGO\n"
            f"IF IS_ROLEMEMBER(N'ldm_report_reader', N'{user}') = 0 "
            f"ALTER ROLE ldm_report_reader ADD MEMBER {_ident(user)};"
        )

    def apply_sql_in_namespace(self, sql_text: str, namespace: str) -> None:
        cur = self._db.cursor()
        try:
            cur.execute("EXEC sp_set_session_context N'ldm.namespace', ?;", namespace)  # type: ignore[attr-defined]
            self._db.script(sql_text, cur)
        except self._db.pyodbc.Error as e:
            raise TargetError(*parse_odbc_error(e)) from e
        finally:
            cur.close()  # type: ignore[attr-defined]
