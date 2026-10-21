# Selective legacy data migration: Db2 (on EKS) -> PostgreSQL (tenant database on the shared RDS)

The demo moves one slice of OtterWorks - the **document-retention history** - out of a Db2
database (a container on EKS standing in for Db2 for z/OS) into the tenant's **existing PostgreSQL
database** on the shared RDS instance (`mig`/`stg`/`arch` schemas), staging unload files in the
tenant's prefix of the shared S3 bucket and running LOAD as **PySpark in local mode inside the
one-shot Kubernetes Job**. Nothing is provisioned in Azure by default; Azure SQL + Blob remain an
optional rehearsal target (`azure: true` overlay, `manifests/r2-after.yaml`). The rest of
OtterWorks is unchanged. Extract and load are ordinary tooling; the engineering that matters is
**proving which source rows are safe to delete** and producing a row-by-row, audit-ready
reconciliation. Db2 stays the system of record until a row is proven.

Binding interfaces for every implementing unit: [`CONTRACTS.md`](CONTRACTS.md).

## Before / after

Two OtterWorks deployments run side by side for the whole talk, built from the same seed:

| | BEFORE (`d24-before`) | AFTER (`d24-after`) |
|---|---|---|
| Kubernetes namespace | `otterworks-d24-before` | `otterworks-d24-after` |
| Hosts | `t-d24-before.otterworks.app` | `t-d24-after.otterworks.app` |
| Db2 (`db2-archive` StatefulSet) | full seed: 1,200,000 DOCARCH / 4,100,000 FILEAUD / 40 RETNPLCY | same seed, then migrated rows **purged** |
| Target | none | schemas `mig`/`stg`/`arch` in the tenant's own `otterworks_d24_after` database (shared RDS); no new database |
| Staging | none | `s3://<demo bucket>/d24-after/<run_id>/` (IRSA-scoped to that prefix) |
| LOAD engine | - | PySpark `local[*]` inside the Job (`execution.load_engine: spark`; `serial` kept for tests) |
| Azure | none | none by default (optional: `azure: true` overlay provisions SQL serverless + Blob) |
| Archive read path | `ARCHIVE_STORE=db2` | `ARCHIVE_STORE=postgresql` |
| Reconciliation report | - | admin dashboard (HTML) + CSV export |

The presenter opens the same archived document in both deployments: BEFORE serves it from Db2,
AFTER from PostgreSQL, with identical audit-trail values (timestamps to 12 fraction digits,
charges to 8 decimals). The AFTER report shows, per source table, extracted / loaded / validated /
purged / failed counts and a failed-row section (source key, rejection rule, SQLSTATE or conversion
error) covering all seven planted failure classes MIG-01..MIG-07. Failed rows stay in Db2. The
report links the Devin sessions that produced the code.

Selection (from `manifest.yaml`, never hard-coded): retention class in `closed-7y` and last access
before `2019-01-01` -> 180,000 DOCARCH, 620,000 FILEAUD, all 40 RETNPLCY rows. The headline failure,
MIG-07, is a storage-charge total that agrees for the table but not per retention class; the
validator checks per class, so table-level agreement alone never passes.

## Architecture

```
            EKS cluster otterworks-dev, namespace otterworks-d24-after
 +---------------------------------------------------------------------+
 |  OtterWorks app (ClusterIP, behind shared ingress-nginx)            |
 |     audit-service  --ARCHIVE_STORE=postgresql-->----------------+    |
 |     report-service --mig.* / arch.* ---------------------------+|    |
 |                                                                ||    |
 |  db2-archive StatefulSet (Db2 11.5, static EBS PV,             ||    |
 |     ClusterIP :50000, NO public endpoint)                      ||    |
 |        ^  EXTRACT (UNLOAD01 fixed-width)  ^ PURGE              ||    |
 |        |                                  |                    ||    |
 |  Kubernetes Job  python -m ldm <stage>                         ||    |
 |     LOAD = PySpark local[*] in the same container (no Spark    ||    |
 |     cluster, operator, Service or UI); other stages serial ----+|----+--> shared RDS + S3
 +---------------------------------------------------------------------+         |
                                                                                  v
            Shared AWS (already provisioned by the platform / tenant deploy)
 +---------------------------------------------------------------------+
 |  RDS PostgreSQL instance, database otterworks_d24_after (tenant's)   |
 |     mig.* run ledger / rejects / validation / purge audit           |
 |     stg.*  staging (raw bytes + converted)   arch.* migrated rows   |
 |  S3 demo bucket, prefix d24-after/<run_id>/ (unload files, report)  |
 |     IRSA role otterworks-ldm-d24-after-job limited to that prefix   |
 +---------------------------------------------------------------------+

 Optional (azure: true overlay only): Azure SQL serverless + Blob staging + Container Apps,
 reached over the public endpoint with a firewall rule for the EKS egress IP (r2-after).
```

### Networking decision (fixed)

Db2 runs as a StatefulSet in the tenant namespace on EKS with **no public endpoint**. The migration
job's execution host is therefore a **Kubernetes Job in the same tenant namespace**, which reaches
the shared RDS endpoint and S3 inside the VPC exactly as the application services do. **EXTRACT and
PURGE always run beside Db2.** With the optional Azure overlay the Job reaches Azure SQL over its
public endpoint (Terraform firewall rule for the EKS NAT egress IPs) and `run_job_in_azure=true`
may move LOAD/VALIDATE/RECONCILE to the Container Apps job; private networking exists behind a
Terraform variable that defaults to off.

### LOAD engine

`execution.load_engine: spark` (default overlays) parses the unload files as bounded slices
(`records_per_slice`) on a PySpark `local[*]` session started inside the Job container: every slice
is converted with the copybook `convert_record()`, malformed records become rejects, duplicate
source keys are resolved per key (first well-formed record in file order wins) and each partition
inserts its rows into `stg.*` through a reopened target connection. Only aggregate counts return to
the driver. `serial` is the same pipeline on one thread and stays the engine for unit tests; both
engines produce identical ledgers and rejects (parity tests in `job/tests/test_postgresql.py`).

### Stages (one job, `python -m ldm <stage>`)

| Stage | Runs on | Does |
|---|---|---|
| EXTRACT | EKS Job (always) | reads the manifest, unloads each table by key range to fixed-width files (COBOL `UNLOAD01`), records per-file row count + SHA-256 and completed ranges; restartable |
| LOAD | EKS Job (PySpark local mode, or serial) | parses records with the copybooks, converts to target types, batch-inserts `stg.*` (source key, raw bytes, converted columns); conversion failures become rejects, the batch continues |
| VALIDATE | EKS Job, or Container Apps job | business hash (same columns both sides), parent present for every child, per-class counts, per-class storage-charge sums to the 8th decimal; only fully validated rows become purge-safe and are promoted to `arch.*` |
| PURGE | EKS Job (always) | deletes only purge-safe keys, audit row written before each delete, transactional batches, stops if intended != validated; dry run unless the namespace overlay sets `purge: true` |
| RECONCILE | EKS Job, or Container Apps job | builds the report from ledger + rejects + purge audit; fails if extracted != loaded + rejected or purged != validated |

Every stage writes counts to the target run ledger (`mig.*` in the tenant's PostgreSQL database) keyed by `run_id` + `namespace`.

## Namespacing

The token `<run>-<state>` (`d24-before`, `d24-after`; regex `^[a-z][a-z0-9]{1,11}-(before|after)$`)
names everything: Kubernetes namespace, Db2 database, S3 bucket/prefix, IRSA job role, the tenant
PostgreSQL database that hosts `mig`/`stg`/`arch`, hostnames, Terraform state keys and the
`namespace` tag (plus, for `azure: true` overlays, the Azure resource group, SQL server, storage
container and Container Apps). Everything is created only by Terraform plus the deploy script and tagged
`namespace`, `owner=otterworks-demo`, `demo=legacy-data-migration`, `expires=<UTC timestamp>`.
`make demo-destroy NS=<token>` destroys both clouds and verifies nothing tagged with the token
remains; a scheduled reaper removes expired tokens. Exact names: `CONTRACTS.md` §3.

## Operations

```
make demo-up NS=d24-before
make demo-up NS=d24-after
make demo-migrate NS=d24-after RUN_ID=r20260924150000
make demo-destroy NS=<token>
make demo-verify-clean NS=<token>
```

## Generalization

Tables, key and hash columns, selection, type overrides and the purge flag live in the manifest;
the source driver, unload command and copybook directory, and the target provider and credentials
are configuration. The target provider is a driver (`job/ldm/drivers/postgresql.py`, `azuresql/`) plus a
type map and DDL directory; a different pair (for example Oracle -> PostgreSQL) is a manifest,
type map and driver change, not a rewrite of the stages.

## Map

| Path | What |
|---|---|
| `CONTRACTS.md` | binding contract (ownership, schemas, CLI, API, Terraform, ops) |
| `manifest.yaml`, `manifests/` | base manifest + per-namespace overlays |
| `source/` | Db2 DDL, copybooks + field derivation, seed spec, UNLOAD01 |
| `job/` | `ldm` package, Dockerfile, type maps, tests |
| `target/postgresql/` | PostgreSQL DDL (default target) |
| `target/sql/` | Azure SQL DDL (optional target) |
| `sessions/` | Devin session links shown in the report |
| `../demos/app/complexity-manifest.json` | MIG-01..07 register |
