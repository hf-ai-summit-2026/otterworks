---
name: incident-responder
description: >
  Repo-specific mechanics for answering a production alert on OtterWorks
  document-service as the on-call first responder. Covers the four armable
  scenarios and what pages for each, the local Compose stack with Prometheus,
  Grafana, Jaeger and Alertmanager, the exact commands to reproduce an alert,
  read the trace and query fan-out, verify a fix with the before/after gate, and
  how the demo resets (disarm, revert, isolated tenant on the shared cluster).
---

# Incident Responder — OtterWorks

Repo-specific mechanics behind the `!incident_responder` Playbook. Auto-loaded
when Devin works in this repository. Everything below is document-service
(`services/document-service/`, Python 3.12, FastAPI, SQLAlchemy async, Alembic).

## The four scenarios on `main`

`main` deliberately ships four production flaws in document-service. They are the
durable before-state, they stay on `main`, and a fix lives on the responder's own
branch. `incident/scenarios.yaml` is the machine-readable source of truth
(what the user sees, what the chart shows, the code cause, the correct fix, the
load profile, the paging alert and its time-to-fire promise).

| Scenario | Paging alert (`page: devin`) | Fires within | Code cause | Fix shape |
|---|---|---|---|---|
| `n-plus-one` | `DocumentListLatencyHigh` (p95 of `GET /api/v1/documents/` > 1 s for 1 m) | 180 s | `app/services/document_service.py` `DocumentService.list_documents` runs one `document_versions` SELECT per document; no index on `documents(owner_id, is_deleted, is_template, updated_at)` or `document_versions(document_id, version_number)` | one batched versions query, one Alembic migration adding both indexes, one test pinning the query count |
| `log-flood` | `RequestLogVolumeNearFull` (request-log bytes / capacity > 0.80 for 30 s) | 240 s | `app/middleware/request_log.py` appends every response body to one JSONL file, no cap, no rotation, raises on write failure | bounded rotation, logging failure never fails the request, test that writes past the cap |
| `cache-leak` | `DocumentServiceMemoryHigh` (RSS / memory limit > 0.75 for 1 m) | 420 s | `app/services/render_cache.py` is a plain dict keyed by (document, version, format) with no eviction | bounded LRU or TTL, test that inserts past the bound |
| `double-run` | `DocumentStatsRollupDuplicated` (`otterworks_rollup_duplicate_windows` > 0) | 240 s | `app/jobs/stats_rollup.py` schedules the rollup in every process with no lock; two replicas insert the same window | PostgreSQL advisory lock or unique `window_start` + `ON CONFLICT DO NOTHING`, test running two rollups for one window |

`n-plus-one` is the flaw the code was shipped with — it is on regardless of any
flag. The other three are gated behind Redis chaos flags
(`app/chaos.py`: `chaos:document-service:{request_log,render_cache}`) or a second
replica, so they are off until armed and fail closed when Redis is unreachable.
`DocumentListQueryFanout` (SQL statements per request > 20) is diagnostic: it
fires alongside `DocumentListLatencyHigh` but does not page.

The armed `log-flood` request log is the flaw, not a feature: it records
response bodies (with credential headers, bearer-like query parameters and
token fields redacted) into a tmpfs on the Compose stack, or the container's
ephemeral filesystem on the isolated tenant's pod, over seeded demo data only.
`make disarm` purges it and the tenant is disposable, so nothing outlives the
run. A real remediation removes body capture or restricts it to a bounded,
access-controlled store — do not turn the flag on against `otterworks-main` or
any tenant holding real data.

Two things that are *not* in scope: `services/admin-service/config/environments/production.rb`
(a different planted bug, see `AGENTS.md`) and anything under `security/`
(other exercises). Do not "fix" the flaw on `main`; work on your own branch.

## Commands

```bash
make incident-up                              # document-service + Postgres/Redis + Prometheus/Grafana/Jaeger/Alertmanager
make incident-up UI=1                         # also api-gateway + web-app so the slowness shows in a browser
make arm SCENARIO=n-plus-one                  # plant the flaw, seed the dataset, start deterministic load
make incident-status                          # firing page=devin alerts and the numbers behind them
make incident-verify SCENARIO=n-plus-one EXPECT=before   # gate: fixture pinned, alert fired in time, before-thresholds met, webhook captured
make incident-verify SCENARIO=n-plus-one EXPECT=after    # gate: source changed, same load, alert clears, after-thresholds met
make incident-simulate RECEIVER=devin         # the exact JSON the Devin Automation webhook received
make incident-load SCENARIO=n-plus-one DURATION=120      # the load profile in the foreground (prints p50/p95/queries per request)
make disarm                                   # stop load, clear flags, restore replicas/logs
make incident-fingerprint                     # fixture/source fingerprints vs incident/expected.yaml (exit 2 on drift)
make incident-record REASON="..."             # re-pin incident/expected.yaml (audited; the reason is committed)
make incident-down                            # stop the stack (volumes kept)
```

`make arm` / `make disarm` are aliases for `make incident-arm` / `make incident-disarm`.
The harness is `incident/incident.py` (run under `uv`, no install step). Its
`verify` exits `0` green, `1` red, and always writes
`incident/reports/<scenario>-<before|after>-<stamp>.json` — on red as well as
green. The reports directory is git-ignored generated output; paste the summary
lines into the PR body rather than committing them.

Ports (Compose, all loopback): document-service `8083`, Postgres `5432`, Redis
`6379`, Prometheus `9090`, Grafana `3001` (`admin` / `otterworks`), Jaeger
`16686`, Alertmanager `9093`, alert sink `9095`, OTLP collector `4318`.
With `UI=1`: api-gateway `8080`, web-app `3000`. Override targets with
`INCIDENT_BASE_URL`, `INCIDENT_PROM_URL`, `INCIDENT_COMPOSE`; `INCIDENT_LOAD_SCALE`
(default `1`) multiplies a scenario's rps and concurrency for a target with less
headroom than the local stack (the local gates always run unscaled).

The fixture dataset is deterministic (`incident/scenarios.yaml` → `seed`): one
owner `6d0c5f5e-7f0f-4a4e-9d0c-1a1c1d3a7000`, 400 documents, 8 versions each,
seeded from `random_seed: 20260924`. Seeding is idempotent on (owner, title).
The load generator signs its own JWT with the Compose `JWT_SECRET`; requests
carry `X-DB-Queries` (SQL statements issued for that request) and
`X-Request-Duration-Ms` response headers, so a single `curl -i` already shows
the fan-out.

## Read telemetry first

Everything document-service exports is in `app/telemetry.py`:
`http_requests_total`, `http_request_duration_seconds` (by `handler`, `method`,
`status`), `otterworks_db_queries_per_request` (histogram by `handler`),
`otterworks_db_query_duration_seconds`, `otterworks_process_resident_memory_bytes`
and `otterworks_process_memory_limit_bytes`, `otterworks_request_log_bytes` and
`otterworks_request_log_capacity_bytes`, `otterworks_render_cache_entries`,
`otterworks_rollup_runs_total` and `otterworks_rollup_duplicate_windows`.

```bash
# the page you were handed
make incident-simulate RECEIVER=devin | jq '.payload.alerts[0] | {labels, annotations, startsAt}'

# p95 and statements per request for the list endpoint, right now
curl -s 'localhost:9090/api/v1/query' --data-urlencode \
  'query=histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{job="document-service",handler="/api/v1/documents/",method="GET"}[2m])))' | jq '.data.result[0].value[1]'
curl -s 'localhost:9090/api/v1/query' --data-urlencode \
  'query=sum(rate(otterworks_db_queries_per_request_sum{handler="/api/v1/documents/"}[2m])) / sum(rate(otterworks_db_queries_per_request_count{handler="/api/v1/documents/"}[2m]))' | jq '.data.result[0].value[1]'

# one slow trace and the SQL spans inside it
curl -s 'localhost:16686/api/traces?service=document-service&operation=GET%20/api/v1/documents/&minDuration=1s&limit=1' \
  | jq '.data[0].spans | map(select(.operationName|startswith("SELECT"))) | length, (.[0].tags[]|select(.key=="db.statement")|.value)'
```

Grafana dashboard: `http://localhost:3001/d/otterworks-incident-responder`
(`observability/grafana/dashboards/incident-responder.json`). The three panels a
reviewer wants to see are request rate (flat), p95 latency (climbing) and SQL
statements per request (stepping from 4 to 104 for a 100-row page; a batched fix
lands at 5, which is the after gate's ceiling). Alert rules
are in `observability/prometheus/incident_alerts.yml`; routing (`page: devin` →
Devin webhook and Slack, everything else → local sink) is in
`observability/alertmanager/alertmanager.yml.tmpl`.

## Reproduce, fix, prove

```bash
make incident-up && make arm SCENARIO=n-plus-one
make incident-verify SCENARIO=n-plus-one EXPECT=before      # red until the alert fires, then green: this is the reproduction
# ... change app/, add alembic/versions/004_*.py, add a test ...
cd services/document-service && poetry install --no-interaction && poetry run ruff check . && poetry run pytest -q tests/test_telemetry.py tests/test_document_service.py
cd ../.. && docker compose -f docker-compose.yml -f docker-compose.infra.yml -f docker-compose.incident.yml up -d --build document-service
make incident-verify SCENARIO=n-plus-one EXPECT=after       # drives the same load for 150 s (SOAK=<s> to change), alert must clear
```

The `after` gate refuses to run against an unchanged source fingerprint, so it
cannot be passed by waiting for the load to stop — and it requires the scenario
to **still be armed**: do not `make disarm` before `EXPECT=after`. It re-applies
the scenario's own conditions (`after_prepare` in `incident/scenarios.yaml`:
purge the request log, recreate the service under the 256m ceiling, restart the
replica on the rebuilt image), checks they hold, drives the same load profile
(or lets the replicas run) for `after_soak_seconds`, then requires the alert
inactive **and** the scenario's `after:` thresholds met (`queries_per_request`
and `p95_seconds` for n-plus-one, `request_log_ratio`, `cache_entries` /
`memory_ratio`, new rollup windows with zero duplicates from the table and the
gauge). Rebuild the image before the `after` run — verifying against the old
container is the most common way to get a meaningless green. Migrations run on
container start (`app/db/migrate.py`), so a new `alembic/versions/004_*.py` is
applied by the rebuild.

The gates never read `nan` as a number. A threshold whose metric has no samples
in the 2 m window fails with `no samples in the 2m window (Prometheus returned
nan/none)`, and the `after` gate additionally requires the offered load to have
reached the service: `request_rate >= 12 rps` (half the pinned 24 rps profile).
Both are diagnostics about the environment, not verdicts on the fix: the load
generator prints `shed=N` when its 24 concurrent slots are all busy, and a host
that sheds most requests after the fix is too small for the unscaled profile
(the local Compose stack with Prometheus, Grafana, Jaeger, Postgres and the
service was verified green on 8 vCPU / 32 GB; on a 2-4 vCPU laptop expect the
before gate to pass and the after gate to trip the load-reached check). Do not
lower the profile or `INCIDENT_LOAD_SCALE` to make the gate pass — the verify
command ignores the scale on purpose — move to a bigger host or the isolated
tenant below and quote that in the PR.

Nine pre-existing failures in `tests/test_documents_api.py` (mutating endpoints
called without an auth header, asserting `200` against a `401`) and
`test_restore_version` are on `main` and are **not** yours to fix; run the
focused files above, and report the full-suite count as "9 failed on `main`,
N failed on the branch" if you run it.

Before/after numbers for the PR body come from the two report files
(`metrics.p95_seconds`, `metrics.queries_per_request`) or from
`make incident-load SCENARIO=n-plus-one DURATION=60` on each build.

## Show it in the browser (n-plus-one)

The gates prove the fix to a machine; a recording proves it to the on-call
engineer. Run the stack with `UI=1` and record the page users complain about,
slow before the fix and fast after, under the same armed load.

```bash
make incident-up UI=1         # adds auth-service, api-gateway, web-app; then runs make incident-ui-login
make arm SCENARIO=n-plus-one  # load must be running while you record
```

- Open `http://localhost:3000/login` in your own browser and sign in as
  `oncall@otterworks.dev` / `OnCall-Demo-1`. That user is the fixture owner
  (`seed.owner_id`), created by `incident/ui-login.sql`; it is local Compose demo
  data only. `make incident-ui-login` re-creates it if the database was reset.
- Open DevTools → Network (filter `documents`, "Disable cache" on), start a
  screen recording, then load `http://localhost:3000/documents` two or three
  times. Click the `documents?page=1&pageSize=50` request so the recording shows
  its **Time** and the `x-db-queries` / `x-request-duration-ms` response headers.
- The web app sends `pageSize`, which document-service ignores, so the browser
  page lists 20 documents (24 statements, ~0.5-0.8 s under load), not the 100
  rows the load generator requests (104 statements, ~2-3 s). Quote the numbers
  the recording shows; do not change the web app to make the page slower.
- After rebuilding document-service, with the scenario still armed (before or
  during `EXPECT=after`; never after `make disarm`), repeat the same steps on the
  same URL: the batched fix brings the same request to 5 statements and a
  fraction of the before time. One recording with both halves, or two short
  ones, labelled before/after.
- Attach the recording to the PR (embed the video file path in the PR body or a
  PR comment so it uploads) next to the Grafana and Jaeger screenshots, with one
  line: `/documents: <before ms>, <before> statements -> <after ms>, <after> statements`.

## The page and the automation

Alertmanager always posts the firing alert to the local sink
(`http://alert-sink:9095/devin`) and, when `DEVIN_WEBHOOK_URL` +
`DEVIN_WEBHOOK_SECRET` are set, also to the Devin Automation webhook trigger
(with `X-Webhook-Secret`); when `SLACK_WEBHOOK_URL` is set it posts to
`#otterworks-alerts` too, otherwise to the sink's `/slack`. So the flow runs
with no external credentials, and in real mode the before gate and
`make incident-simulate` (which prints exactly what the Automation received)
still read the mirrored copy. The sink is an intentionally
unauthenticated, disposable capture buffer: it is reachable only on the Compose
network and on the host's loopback (`127.0.0.1:9095`), and must never be
published beyond the laptop — a real deployment posts to the Devin Automation
webhook and Slack directly. The Automation's trigger, prompt,
connectors, ACU budget and network policy are documented in
`docs/incident-responder/automation.md`; the prompt tells the session to post
the RCA as a reply in the alert's Slack thread (`channel` and `ts` are in the
Slack payload) before opening the PR.

## On the shared EKS cluster

The local Compose stack is the default and is all a laptop needs. On the
shared `otterworks-dev` cluster the incident runs across two tenants: the page
fires on the perpetual **`main` tenant** (`t-main.otterworks.app`, the golden
app with its planted flaws), and the fix lands on the long-lived **`incident`
tenant** (branch `demo-incident`, which tracks `main`). `main` is never fixed,
so the flow re-arms indefinitely; the alert's `fix_branch` label carries the
handoff from one to the other.

| | Paging tenant | Fix tenant |
|---|---|---|
| Branch | `main` | `demo-incident` (`branch_tenant_id` strips `demo-`; kept equal to `main` between runs) |
| Tenant id | `main` | `incident` — pass `incident`, not `demo-incident`, to the tenant scripts |
| Namespace | `otterworks-main` (perpetual, no TTL) | `otterworks-incident` (72 h TTL, `demo/expires-at` annotation) |
| Hosts | `t-main.otterworks.app`, `api-t-main.otterworks.app` | `t-incident.demo.otterworks.app`, `api-t-incident.demo.otterworks.app` — branch tenants live under `demo.otterworks.app` |
| Values overlay | `infrastructure/helm/tenant-values/main/document-service.yaml`: PrometheusRule (+ `fix_branch: demo-incident` on every alert), dashboard, tracing, Recreate, 512Mi | `infrastructure/helm/tenant-values/incident/document-service.yaml`: same minus the label |
| What is allowed | fixture seed + list load only (`incident/tenant.sh arm main`); no chaos flags, no config, no code — see `AGENTS.md` | anything a `demo-*` branch may do |
| Before-state | `origin/main` | `git rev-parse origin/demo-incident` (equal to `main` before a fix merges) |

`scripts/deploy-tenant.sh` applies `infrastructure/helm/tenant-values/<tenant-id>/<service>.yaml`
with `-f` when it exists, so CD and manual deploys get the same values. The
PrometheusRule renders `observability/prometheus/incident_alerts.yml` and the
dashboard ConfigMap renders `observability/grafana/dashboards/incident-responder.json`
from chart-local copies, both scoped to the release namespace (`otterworks-main`
or `otterworks-incident`). After editing either source run
`make incident-chart-sync`; CI's `incident-chart-sync` job
(`make incident-chart-check`) fails on drift.

### Page t-main (the one-line arm)

```bash
incident/tenant.sh arm main          # seed the 400-doc fixture (idempotent), run the list load 15 min through the ingress
incident/tenant.sh status main       # one list call: x-db-queries: 104, x-request-duration-ms > 1000 while loaded
incident/tenant.sh disarm main       # stop the load; the alerts resolve on their own
```

`DocumentListLatencyHigh{namespace="otterworks-main", branch="main",
fix_branch="demo-incident", page="devin"}` fires about 90 s after `arm` and
Alertmanager posts it to the Devin Automation webhook. The same script arms
`incident` (`incident/tenant.sh arm incident`) when you want to show the fix
tenant slow and then fast. The fixture lives under its own owner id
(`incident/scenarios.yaml` `seed.owner_id`), so nothing a t-main user owns is
touched; `make incident-reset-fixture` against the port-forward removes it.

### Create or redeploy the tenant

```bash
git push origin <before-sha>:demo-incident     # .github/workflows/cd-tenant.yml builds + deploys
kubectl -n otterworks-incident get pods,ingress
```

If the CD runner Job fails (`kubectl -n otterworks-platform logs job/deploy-incident-<epoch>`;
it needs `monitoring.coreos.com` RBAC on its ClusterRole and `GITHUB_TOKEN` +
`REPO_HTTPS_URL` to check out the branch — see `docs/MULTI-TENANT-RUNBOOK.md`),
deploy the same branch from a checkout with the same host suffix CD uses, so
external-dns (whose domain filter is `demo.otterworks.app`) keeps the records.
The Actions `build` job has already pushed `otterworks/document-service:tenant-incident`,
which the script picks up:

```bash
git checkout demo-incident
export AWS_DEFAULT_REGION=us-east-1 DB_PASSWORD='<shared RDS master password>'
scripts/deploy-tenant.sh incident --profile core --host-suffix demo.otterworks.app --ttl 72h --branch demo-incident
```

Leave `JWT_SECRET` / `SECRET_KEY_BASE` unset on a redeploy: the script reuses the
values already in the tenant's `api-gateway-secrets` / `admin-service-secrets`
and only generates them for a brand-new tenant. Every service that mints or
verifies a token must share one `JWT_SECRET`, and Helm only restarts the pods
whose spec changed — a redeploy that minted a fresh secret left api-gateway and
auth-service verifying against the old one, and every request through the
ingress answered `401 token signature is invalid` while document-service
(port-forwarded) still worked. If that happens anyway, confirm the three
secrets agree and restart the stale Deployments:

```bash
for s in api-gateway auth-service document-service; do
  kubectl -n otterworks-incident get secret $s-secrets -o jsonpath='{.data.JWT_SECRET}' | base64 -d | sha256sum
done
kubectl -n otterworks-incident rollout restart deploy/api-gateway deploy/auth-service
```

### Seed, load and read the headers

document-service's Service listens on 8083. The harness signs its JWT with
`JWT_SECRET` from the environment, so export the tenant's:

```bash
# what incident/tenant.sh does, by hand (swap otterworks-main / api-t-main.otterworks.app for the paging tenant):
kubectl -n otterworks-incident port-forward svc/document-service 8083:8083 &
export JWT_SECRET="$(kubectl -n otterworks-incident get secret document-service-secrets -o jsonpath='{.data.JWT_SECRET}' | base64 -d)"
INCIDENT_BASE_URL=http://localhost:8083 make incident-seed
export INCIDENT_LOAD_SCALE=0.25
INCIDENT_BASE_URL=https://api-t-incident.demo.otterworks.app make incident-load SCENARIO=n-plus-one DURATION=180

OWNER=6d0c5f5e-7f0f-4a4e-9d0c-1a1c1d3a7000   # incident/scenarios.yaml seed.owner_id
TOKEN="$(uv run --quiet --with pyjwt==2.9.0 python -c "import jwt,os,time;o='$OWNER';print(jwt.encode({'user_id':o,'sub':o,'exp':int(time.time())+3600},os.environ['JWT_SECRET'],algorithm='HS256'))")"
curl -s -D - -o /dev/null -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8083/api/v1/documents/?owner_id=$OWNER&page=1&size=100"
# x-db-queries: 104    x-request-duration-ms: > 1000 while the load runs
```

`INCIDENT_LOAD_SCALE=0.25` turns the catalog's 24 rps / 24 concurrency into
6 / 6. The tenant runs one document-service replica with a 500m CPU limit (one
uvicorn worker) behind the shared ingress, and the full laptop profile saturates
it even after the fix — p95 stays in seconds and most requests are shed, which
says nothing about the query fan-out. At 6 / 6 the before-state still pages
(104 statements, ~2 s per request, p95 well above the 1 s rule) and the fixed
build settles at 5 statements and ~150 ms client / ~60 ms server p50, so the
recovery is visible on the same Grafana panel. The scale is recorded in
`incident/.state/armed.json` and the load log line; the local Compose gates keep
the unscaled profile.

### Shared Grafana, Jaeger, Alertmanager

The stack lives in namespace `monitoring` (not this repository). Ingress hosts
require the platform's login; port-forwards work with cluster access alone:

| Tool | Ingress | Port-forward |
|---|---|---|
| Grafana dashboard `ir-otterworks-incident` | `https://grafana.otterworks.app/d/ir-otterworks-incident` | `kubectl -n monitoring port-forward svc/prometheus-grafana 13000:80` → `http://localhost:13000/d/ir-otterworks-incident` |
| Jaeger, service `document-service`, operation `GET /api/v1/documents/` | `https://jaeger.otterworks.app/search?service=document-service` | `kubectl -n monitoring port-forward svc/jaeger 16686:16686` → `http://localhost:16686/search?service=document-service` |
| Alertmanager | `https://alertmanager.otterworks.app/#/alerts?filter=%7Bnamespace%3D%22otterworks-incident%22%7D` | `kubectl -n monitoring port-forward svc/prometheus-alertmanager 19093:9093` |
| Prometheus | `https://prometheus.otterworks.app` | `kubectl -n monitoring port-forward svc/prometheus-prometheus 19090:9090` |

p95 behind `DocumentListLatencyHigh`:

```promql
histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{job="document-service",namespace="otterworks-incident",handler="/api/v1/documents/",method="GET"}[2m])))
```

`DocumentListLatencyHigh` (`page: devin`, routed to the Devin webhook and
Slack) and `DocumentListQueryFanout` go active about 1 m after p95 crosses 1 s.

### A fix reaches the fix tenant

The alert's `fix_branch` label (`demo-incident` on t-main's alerts) names the
PR base: branch the fix from `demo-incident` and open the PR against it, never
against `main`. Merging it pushes `demo-incident`; `cd-tenant.yml` rebuilds
document-service (the change is under `services/document-service/**`),
re-points `tenant-incident` and redeploys `otterworks-incident`. Then
`incident/tenant.sh arm incident` and `incident/tenant.sh status incident`: the
header drops to 5 statements and no alert fires for that namespace, while
`incident/tenant.sh status main` still shows 104 — same load, fixed branch
versus golden. t-main's own alert resolves when its load is disarmed.

## Reset and revert

- `make disarm` (alias of `make incident-disarm`) stops the load, clears chaos
  flags, purges the request log, removes the second replica and restarts
  document-service. It does not touch the database fixture (idempotent seed)
  or the PR.
- On the cluster: `incident/tenant.sh disarm main` (and `... disarm incident`)
  stops the load; nothing was planted, so there is nothing else to undo on
  t-main.
- Reset the fix tenant after a fix was merged by moving the branch itself: force
  `demo-incident` back to `main` (or `git revert <merge-sha>` on it), which
  rebuilds and redeploys the before-state image, then `make incident-disarm`
  locally:

  ```bash
  git push --force origin origin/main:demo-incident
  make incident-disarm
  ```

  CD redeploys the tenant from the branch, so the alert's `branch` label keeps
  matching the running image. Do **not** reset the tenant with
  `scripts/deploy-tenant.sh incident --image-tag <tag>` or a `BUG_IMAGE_TAG_*`
  override: the label would still say `demo-incident` while the pods run an
  image that branch did not build, and the responder's local reproduction
  would disagree with the tenant. Then `make arm SCENARIO=...` again.
  Locally, `git checkout <before-sha> -- services/document-service` and
  `make incident-up` rebuilds the before-state image.
- If the fix carried a migration (the reference fix adds `004_document_list_indexes`),
  downgrade the database **before** rebuilding the before-state image, while the
  fix's code is still present: `docker compose -f docker-compose.yml
  -f docker-compose.infra.yml -f docker-compose.incident.yml exec -T -w /app
  document-service sh -c 'PYTHONPATH=/app alembic downgrade 003'`. Otherwise the
  before-state container exits with `Can't locate revision identified by '004'`
  at boot because the database is stamped past the revisions it ships.
- Tear the tenant down with `scripts/teardown-tenant.sh incident`.
- `make incident-verify SCENARIO=<name> EXPECT=before` must go green again
  after any reset; if it reports fixture drift, something other than the fix
  changed and the recorded evidence (`incident/expected.yaml`) explains what is
  pinned.
