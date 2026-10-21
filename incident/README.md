# document-service incident runbook

Every incident alert on document-service carries a `runbook_url` that lands on
this page. The section named after the alert's `scenario` label says what a
user is seeing, what the chart is showing, where the cause is in code and what
a correct fix looks like — with the numbers the verification gate holds the
service to. The catalog these sections are rendered from is
[`scenarios.yaml`](scenarios.yaml); the commands are in the
[`incident-responder` Skill](../.agents/skills/incident-responder/SKILL.md).

Every scenario is armable on a laptop (`make incident-up`, then
`make incident-arm SCENARIO=<name>`) and pages within the stated time. Nothing
here is a fault of the shared cluster; the flaws are planted in `main` on
purpose and are not fixed there — fixes ship on a branch and deploy only to an
isolated tenant.

| Alert | Scenario | `for` | Fires within (after arm) | Symptom |
|---|---|---|---|---|
| `DocumentListLatencyHigh` (pages) | [`n-plus-one`](#n-plus-one) | 1 m | 180 s | document list p95 > 1 s, request rate flat |
| `DocumentListQueryFanout` | [`n-plus-one`](#n-plus-one) | 1 m | 180 s | > 20 SQL statements per list request |
| `RequestLogVolumeNearFull` (pages) | [`log-flood`](#log-flood) | 30 s | 240 s | request-log volume > 80 % |
| `DocumentServiceErrorRateHigh` (pages) | [`log-flood`](#log-flood) | 1 m | follows the volume filling | 5xx ratio > 5 % |
| `DocumentServiceMemoryHigh` (pages) | [`cache-leak`](#cache-leak) | 1 m | 420 s | RSS > 75 % of the memory limit |
| `DocumentStatsRollupDuplicated` (pages) | [`double-run`](#double-run) | 30 s | 240 s | a rollup window computed twice |

## Triage order

1. Read the page: `alertname`, `scenario`, `service`, `severity`, `summary`
   (the metric and its threshold), `startsAt`, and the `dashboard_url`,
   `traces_url`, `runbook_url` annotations.
2. Telemetry before code: the Grafana dashboard for the symptom and for what is
   *not* moving (request rate, deploys), Jaeger for where the time or resource
   goes, `make incident-status` for the live numbers.
3. Reproduce locally: `make incident-up`, `make incident-arm SCENARIO=<scenario>`,
   `make incident-verify SCENARIO=<scenario> EXPECT=before` must go green.
4. Follow the span name or SQL text back to the emitting function; `git log -S`
   on it.
5. Smallest fix, one regression test, rebuild, then
   `make incident-verify SCENARIO=<scenario> EXPECT=after` under the same load.
6. `make incident-disarm` when done. Never silence the alert or change the
   rule, the threshold, the scenario or the recorded evidence to go green.

## n-plus-one

**Document list slows to a crawl.** Alerts `DocumentListLatencyHigh` (pages)
and `DocumentListQueryFanout`, both `for: 1m`; the page arrives within 180 s of
arming.

- **What the user sees.** Opening "My documents" takes seconds; the spinner sits
  at 2–3 s while the rest of the app is snappy. Nothing errors, so nobody files
  a bug — they just complain.
- **What the chart shows.** Request rate flat; p95 of `GET /api/v1/documents/`
  climbing from ~60 ms to ~2.4 s; SQL statements per request stepping from 4 to
  104 on a 100-row page (`x-db-queries: 104`); one Jaeger trace fanning into a
  hundred identical `SELECT`s on `document_versions`.
- **Code cause.** `DocumentCrud.list_documents`
  (`services/document-service/app/services/document_crud.py`) runs one
  versions query per document in a Python loop, and the schema lacks an index
  covering the owner listing order on `documents` and a composite index on
  `document_versions(document_id, version_number)`.
- **Correct fix.** One batched query for the recent versions of the whole page
  (window function or `IN` + `ORDER BY`), a new Alembic migration adding the two
  indexes without touching `001_initial_schema.py`, and a regression test
  asserting the list endpoint issues a constant number of statements regardless
  of page size. Statements per request land at 5.
- **Gate.** Before: ≥ 50 statements/request and p95 ≥ 1.0 s while the alert
  fires. After, same load: ≤ 5 statements/request, p95 ≤ 0.5 s, alert inactive.
- **Load.** `GET /api/v1/documents/?size=100`, 24 concurrent, 24 rps, against
  the 400-document / 8-versions fixture.

## log-flood

**Debug request log fills the disk.** Alert `RequestLogVolumeNearFull` (pages,
`for: 30s`, within 240 s of arming), then `DocumentServiceErrorRateHigh` once
the volume is full.

- **What the user sees.** A support engineer enabled per-request logging to
  debug a customer ticket. Minutes later every document request returns HTTP
  500.
- **What the chart shows.** `otterworks_request_log_bytes` rising in a straight
  line to the volume capacity, then the 5xx rate jumping from 0 % to 100 % at
  the moment it hits the ceiling.
- **Code cause.** `app/middleware/request_log.py` appends the full response body
  of every request to one JSONL file with no size cap, no rotation, and no
  fallback when the write fails. The flag that turns it on is the chaos key
  `chaos:document-service:request_log` in the tenant's Redis.
- **Correct fix.** Rotate at a bounded size with a fixed number of backups (or
  truncate bodies), never fail the request because logging failed, plus a test
  that writes past the cap and asserts the file set stays bounded.
- **Gate.** Before: volume ≥ 80 % full. After, from an empty volume and the same
  240 s of load: volume ≤ 25 % full, error ratio ≤ 1 %, alert inactive.
- **Load.** `GET /api/v1/documents/?size=100`, 8 concurrent, 8 rps.

## cache-leak

**Render cache grows until the pod restarts.** Alert
`DocumentServiceMemoryHigh` (pages, `for: 1m`, within 420 s of arming under a
256 MiB limit).

- **What the user sees.** Exports get slower through the day; eventually the
  service restarts and every in-flight request fails.
- **What the chart shows.** `otterworks_render_cache_entries` climbing
  monotonically; `otterworks_process_resident_memory_bytes` tracking it toward
  the container memory limit; the container restarts once it crosses.
- **Code cause.** `app/services/render_cache.py` is a plain dict keyed by
  (document, version, format) with no eviction; every edit creates a new version
  and a new entry, and nothing ever removes the old ones. Enabled by the chaos
  key `chaos:document-service:render_cache`.
- **Correct fix.** Bounded cache (LRU with a max entry count or byte budget, or
  a TTL) and a test that inserts past the bound and asserts the size stays
  capped.
- **Gate.** Before: ≥ 2000 cache entries. After, same 256 MiB ceiling and 420 s
  of the same edit/export load: ≤ 1000 entries, RSS ≤ 70 % of the limit, alert
  inactive.
- **Load.** edit-then-export flow, 12 concurrent, 20 rps.

## double-run

**Hourly rollup runs twice.** Alert `DocumentStatsRollupDuplicated` (pages,
`for: 30s`, within 240 s of starting the second replica).

- **What the user sees.** The usage report shows exactly double the documents
  and words for every hour since the last deploy.
- **What the chart shows.** `otterworks_rollup_runs_total` incrementing on two
  instances for the same window; `otterworks_rollup_duplicate_windows` going
  from 0 to 1, 2, 3…
- **Code cause.** `app/jobs/stats_rollup.py` schedules the rollup in every
  process with no coordination; two replicas both compute and insert the same
  window. (A same-host restart reuses its own row; two hosts do not.)
- **Correct fix.** Take a PostgreSQL advisory lock (or a unique constraint on
  `window_start` with `ON CONFLICT DO NOTHING`) around the rollup, plus a test
  that runs two rollups for one window concurrently and asserts a single row.
- **Gate.** Before: ≥ 1 duplicate window. After, duplicates purged and both
  replicas running for 200 s: ≥ 2 new windows landed, 0 new duplicates, gauge
  at 0, alert inactive.

## Where the page goes

Alertmanager routes every `page: devin` alert to two receivers: the Devin
Automation webhook (starts the first-responder session, no human prompt) and a
Slack channel for the on-call engineer. `make incident-simulate` prints the
exact webhook payload the last page delivered locally
(`RECEIVER=slack` for the Slack form); on the shared cluster the same payloads
are in the `alert-sink` pod logs in namespace `monitoring`. The automation's
trigger, prompt, budget and network policy are in
[`docs/incident-responder/automation.md`](../docs/incident-responder/automation.md).
