# `ldm` — selective legacy data migration job

Owned by the **job** unit (CONTRACTS.md §9, §13.2). Python 3.12 package implementing the staged
Db2 -> PostgreSQL (default; Azure SQL optional) migration with a run ledger, row-level rejects, purge audit and reconciliation.

```
python -m ldm <extract|load|validate|purge|reconcile|all> --manifest <path> --namespace <token> --run-id <id>
python -m ldm init --manifest <path> --namespace <token> [--apply-sql <file.sql> ...]
```

Exit codes: `0` success, `1` unexpected / unreachable source or target, `2` reconciliation arithmetic
failure, `3` purge guard, `4` configuration (manifest, token, env, type map, copybook, migration disabled).

## Layout

| Path | Purpose |
|---|---|
| `ldm/config.py` | strict pydantic manifest + overlay (deep merge, unknown keys rejected, token/overlay consistency) |
| `ldm/typemap.py`, `typemaps/db2-to-postgresql.yaml`, `typemaps/db2-to-azuresql.yaml` | type-mapping table with per-column `type_overrides` |
| `ldm/copybook.py`, `ldm/convert.py` | COBOL copybook parser (PIC X / display / COMP / COMP-3) and field conversion (cp037 strict, DECIMAL range, low-values dates, TIMESTAMP(12)) |
| `ldm/hashing.py` | business hash, identical in Python (raw source rows, serial and Spark) and in target SQL (PostgreSQL `sha256(convert_to(...))`, T-SQL `HASHBYTES`) |
| `ldm/drivers/base.py` | `SourceDriver` / `TargetDriver` protocols; Oracle / PostgreSQL are additive implementations |
| `ldm/drivers/db2.py` | Db2 via `ibm_db` (SQLCODE/SQLSTATE surfaced, transactional purge with `MIGAUDIT.PURGE_AUDIT`) |
| `ldm/drivers/postgresql.py` | PostgreSQL via `psycopg` (default target; `mig`/`stg`/`arch` in the tenant's existing database, SQLSTATE `23505` -> `DUPLICATE_KEY`) |
| `ldm/drivers/factory.py` | picklable `TargetSpec` so Spark partitions reopen the target driver |
| `ldm/drivers/azuresql/` | Azure SQL via `pyodbc` + ODBC Driver 18 (SQL or managed-identity auth), optional; `AzureSqlTarget` facade over per-concern collaborators (connection, schema, ledger, key ranges, staging/rejects, validation, purge audit/reconcile) |
| `ldm/engines/spark_load.py` | PySpark local-mode LOAD engine: bounded slices, `convert_record()` per record, duplicate/reject routing, per-partition inserts, aggregate counts only |
| `ldm/drivers/fakes.py` | in-memory drivers used by the tests |
| `ldm/stages/*.py` | `init`, `extract`, `load`, `validate`, `purge`, `reconcile` |
| `ldm/staging.py` | local staging dir, S3 staging (`{namespace}/{run_id}/` prefix in the shared bucket, default) and optional Azure Blob container |
| `Dockerfile` | `python:3.12-slim` + OpenJDK 17 (PySpark) + psycopg + boto3 + ibm_db clidriver + GnuCOBOL; `--build-arg WITH_AZURE=1` adds msodbcsql18/pyodbc/azure SDKs; build from the repo root |

## Stage semantics

- **extract** — manifest-driven predicate (never hard-coded), keys split into `batch_size` ranges recorded
  in `mig.key_ranges`; each range unloaded through `source.unload_command` (UNLOAD01 wrapper) or the
  built-in fixed-width writer, with `.cnt` / `.sha256` and row/byte/hash verification. Re-running the
  same `run_id` skips completed ranges.
- **load** — copybook slices -> typed values -> `stg.*` with `raw_bytes`; a conversion failure rejects the
  row (`mig.rejects` with field, raw bytes, error, SQLSTATE) and never aborts the batch; a source key
  already in `stg`/`arch` is `DUPLICATE_SOURCE_KEY`. Enforces `extracted = loaded + rejected`.
- **validate** — business hash source vs target (`HASH_MISMATCH`), FILEAUD parent presence
  (`ORPHAN_PARENT_NOT_SELECTED`), per-retention-class counts and exact `Decimal` charge sums
  (`CLASS_COUNT_MISMATCH` / `CLASS_TOTAL_MISMATCH`, so a table-level match cannot hide a class-level
  disagreement). A key already in `arch.*` for this namespace with a different business hash is
  `ARCHIVE_CONFLICT` (kept in source, never purged); an identical archived copy is an idempotent re-run.
  Only fully validated rows get `purge_safe = 1` and are promoted to `arch.*`.
- **purge** — dry run unless the overlay sets `purge: true`; all data tables are guarded
  (`purge_safe` count == ledger `validated`) before any delete, else exit 3 with nothing deleted. Every key
  is written to `mig.purge_audit` (Azure) and `MIGAUDIT.PURGE_AUDIT` (Db2, same unit of work as the
  `DELETE`); a batch whose delete count differs is rolled back. Reference tables are never purged. On
  resume, keys already committed to `MIGAUDIT.PURGE_AUDIT` are marked `PURGED` instead of re-deleted.
- **init** — applies `target.ddl_dir`, the optional reader user, then `--apply-sql` files. Those files
  must be `.sql` files under the migration tree (the manifest's repo root); each is logged with its SHA-256.
- **reconcile** — per-table extracted / loaded / validated / purged / failed from ledger, rejects, purge
  audit; failure details with rule, stage, field, SQLSTATE and error; class-total evidence; session links
  from `report.sessions_glob` plus `DEVIN_SESSION_LINKS` (`label=url,...`). Writes JSON (report API
  shape), CSV and HTML under `LOCAL_STAGING_DIR/<blob_prefix>` and the staging container. Exit 2 when
  `extracted != loaded + rejected` or `purged != validated`. Staging rows are deleted before the run is
  marked `CLOSED`, so a failed cleanup leaves the run re-runnable.

Every stage applies `target.ddl_dir` first (checksum-tracked in `mig.schema_version`) and writes
`mig.stage_log` rows with `LDM_HOST` (`eks` | `aca` | `local`).

## Develop

```sh
cd migration/job
python -m pip install -e '.[dev,postgresql,s3,spark]'   # add [db2] / [azuresql] for the real source / Azure drivers
ruff check . && ruff format --check . && pytest -q
# PostgreSQL-backed tests (serial vs Spark parity, duplicate keys, restart) need a server:
docker run -d --name ldm-pg -e POSTGRES_PASSWORD=ldm -e POSTGRES_USER=ldm -e POSTGRES_DB=ldm -p 55432:5432 postgres:16
LDM_TEST_PG_HOST=localhost LDM_TEST_PG_PORT=55432 pytest -q tests/test_postgresql.py
docker build -f migration/job/Dockerfile -t ldm:dev ../..   # from repo root
```

The tests use `ldm/drivers/fakes.py` and the real copybooks/manifests; they cover MIG-01..MIG-07, the
purge guard, the reconciliation arithmetic failure and resume by key range. Chart:
`infrastructure/helm/migration-job`.
