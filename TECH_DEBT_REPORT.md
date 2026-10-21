# Tech-Debt Audit — Backend Services

Scope: `api-gateway`, `search-service`, `collab-service`, `admin-service`, `audit-service`.
Out of scope: `report-service` (intentional upgrade exercise) and all other services.

Planted bugs and chaos mechanisms were **not** changed. That covers Redis `chaos:*` flags, the
search `suggest_500` crash path, the gateway `internal/chaos` latency injection, the admin
`ChaosController`/`ChaosProbeService`, and the planted Rails 7.1 logger bug in
`admin-service/config/environments/production.rb`. Auth and security behavior (JWT handling,
CORS origins, rate limits, owner scoping) was also left alone because the DAST labs use it.
Where intent was unclear, the item is documented below and the code was not changed.

## Summary

| Service | Lint | Tests | Dependency vulns (before → after) | Commits |
|---|---|---|---|---|
| api-gateway | `golangci-lint` clean, `gofmt` clean (were: 9 errcheck, 2 gofmt) | `go test -race ./...` pass | govulncheck: 7 modules + stdlib → 4 modules + stdlib (all remaining fixes need Go ≥ 1.23) | 3 |
| search-service | `ruff check .` clean on ruff 0.9.10 and 0.17.1 | `pytest` 41 pass | pip-audit: 13 advisories in 7 pkgs → 0 | 3 |
| collab-service | `eslint` clean, `tsc` clean | `jest` 45 pass, open-handle leak fixed | npm audit: 71 → 61 (prod-only: 19, from 2 packages that need major migrations) | 3 |
| admin-service | RuboCop crashed on load → runs; 120 → 58 offenses | `rspec` 120 examples, 0 failures | bundle-audit: 2 gems → 0 | 4 |
| audit-service | `dotnet format --verify-no-changes` clean (was: 4 whitespace errors) | `dotnet test` 53 pass | NuGet: 3 vulnerable pkgs (incl. transitive) → 0 | 2 |

`make lint`: every line for a scoped service passes (`golangci-lint run`, `ruff check .`,
`npm run lint`). The aggregate target still stops early, at `services/auth-service`
(`./gradlew spotlessCheck` fails with `GradleWrapperMain` not found because the wrapper jar is
missing). That failure exists on `main`, and auth-service is out of scope.

`make test`: I ran the same commands per service: `go test ./...`, `pytest`, `npm test`,
`bundle exec rspec` (in `ruby:3.3-slim` against a Postgres container) and `dotnet test`.

## Runtime / platform EOL (highest-priority follow-ups)

| Runtime | Status (as of 2026-10) | Recommendation |
|---|---|---|
| Go 1.22 (api-gateway) | Unsupported since Go 1.24 shipped. govulncheck reports stdlib vulns in `net/http`, `crypto/tls`, `crypto/x509`, `html/template`, `net/url` and others, all fixed only in newer Go | Move to Go 1.25: `go.mod`, `Dockerfile` (`golang:1.22-alpine`), CI `setup-go`. This also unblocks the remaining module upgrades. |
| Node.js 20 (collab-service) | EOL April 2026 | Move to Node 22 LTS or 24 LTS (`Dockerfile`, CI, `@types/node`). |
| .NET 8 (audit-service) | LTS ends November 2026 | Plan the move to .NET 10 LTS. The IBM Db2 provider (`Net.IBM.Data.Db2-lnx`) needs a .NET 10 build first. |
| Alpine 3.19 (api-gateway runtime image) | EOL | Bump the runtime base image along with the Go upgrade. |
| Ruby 3.3 / Rails 7.1 (admin-service) | Supported | Rails 7.2 removes `Rails.application.secrets`; see admin-service below. |
| Python 3.12 (search-service) | Supported | — |

---

## api-gateway (Go 1.22 / Chi)

**Fixed**
- `gofmt` on `internal/config/config.go` and `internal/proxy/router.go` (struct alignment only).
- errcheck findings from `golangci-lint`:
  - JSON error/health writers (`health/handler.go`, `middleware/jwt.go`, `middleware/ratelimit.go`, `proxy/router.go` ×3) now explicitly discard the `Encode` error with `_ =`. Headers are already written at that point, so nothing can be returned to the client.
  - `cmd/server/main.go`: `exporter.Shutdown(ctx)` on the tracer-init failure path is now checked and logged.
  - Tests (`cors_test.go`, `circuitbreaker_test.go`): explicit discards.
- Dependencies (no API changes needed; build and tests pass):
  - `golang-jwt/jwt/v5` 5.2.1 → 5.3.1 (fixes excessive memory allocation in header parsing, GO-2025-3553)
  - `redis/go-redis/v9` 9.5.1 → 9.17.3 (fixes out-of-order responses on `CLIENT SETINFO` timeout)
  - `go-chi/chi/v5` 5.0.12 → 5.2.3
  - `otel` / `otel/sdk` / `otlptracehttp` 1.24.0 → 1.33.0, `otelhttp` 0.49.0 → 0.58.0
  - `testify` 1.8.4 → 1.10.0
  - The `go` directive moved from `1.22` to `1.22.7` (minimum for otel 1.33), and `toolchain go1.22.12` was added. `golang:1.22-alpine` still builds it.

**Deferred**
- These advisories are still open, and each fix needs **Go ≥ 1.23**: `chi` ≥ 5.3.0, `otel/sdk`/`otlptrace` ≥ 1.40, `golang.org/x/net` ≥ 0.38, newer `grpc`, plus the Go stdlib CVEs. Do them together with the Go 1.25 upgrade.
- `rs/zerolog` latest (1.35) needs Go 1.23; left on the current version.

**Static review**
- No TODO/FIXME/HACK markers. No hardcoded secrets: `JWT_SECRET` is required by `Config.Validate()`.
- `internal/chaos` (Redis-driven latency injection) left as is.

**Coverage gaps**
- `cmd/server` and `internal/config` have no tests. `Config.Validate()`, `ServiceRoutes()` and env parsing are untested, even though they decide routing and whether JWT is enforced.

---

## search-service (Python 3.12 / Flask 3.0)

**Fixed**
- Dependencies (pip-audit now clean; 41 tests pass):
  - `flask` 3.0.2 → 3.1.3
  - `flask-cors` 4.0.2 → 6.0.0. This is a major bump, but the only usage is `CORS(app, origins=[...])`, which behaves the same; the 6.0 changes are to path-regex matching.
  - `marshmallow` 3.21.1 → 3.26.2 (stays on 3.x)
  - `requests` 2.31.0 → 2.33.0
  - `python-dotenv` 1.0.1 → 1.2.2
  - `urllib3` 2.7.0 → 2.8.0
  - `pytest` 8.1.1 → 9.0.3 (dev only)
- `pytest` and `pytest-flask` moved out of runtime `requirements.txt` into `requirements-dev.txt`. The production image no longer installs test tooling.
- `Makefile` `build-search` ran `pip install -e .`, but the service has no `pyproject.toml`/`setup.py`, so the target always failed. It now runs `pip install -r requirements-dev.txt`.
- Ruff: the import block in `app/main.py` is sorted. The three intentional broad `except Exception` blocks now carry `# noqa: BLE001` with a reason:
  - `_chaos_active`: Redis down means chaos is off.
  - Startup index creation: the app must boot without MeiliSearch.
  - `MeiliSearchService.ping`: any failure means unhealthy.

  Ruff 0.17.1 flags these with no repo config; ruff 0.9.10 does not.

**Deferred / documented**
- There is no ruff config (`pyproject.toml`/`ruff.toml`) and no pinned ruff version, so lint results depend on whichever ruff is installed. `ruff format --check` would reformat 10 files; I didn't apply it to avoid unrequested churn. Recommendation: add `pyproject.toml` with a pinned ruff version and rule set, then do a single formatting commit.
- Some dependencies are old but have no advisories: `opentelemetry-*` 1.23/0.44b0, `boto3` 1.34.69, `meilisearch` 0.31.6, `gunicorn` 22.0.0, `structlog` 24.1.0. Upgrade them as a batch with a smoke test against MeiliSearch.
- The CI `search-service` job runs only pytest, not ruff.
- The intentional `chaos:search-service:suggest_500` crash path in `app/api/search.py` was not changed.

**Coverage gaps**
- `.coveragerc` sets `fail_under = 0`, so coverage is never enforced. The suite uses mocks rather than a real MeiliSearch; consider a small contract or smoke test against a real instance.

---

## collab-service (Node 20 / Socket.IO / Yjs)

**Fixed**
- `npm audit fix` (lockfile only, non-breaking): 71 → 62 vulnerabilities. Covers `socket.io-parser`, `engine.io`, `body-parser`, `proxy-addr`, `fast-copy`, `@grpc/grpc-js`, and others.
- `uuid` ^9.0.1 → ^11.1.1 (fixes GHSA for `uuid` < 11.1.1). The only usage is `v4` in `document-store.ts`, which is unchanged. `@types/uuid` was removed because uuid 11 ships its own types. Total is now 61.
- Jest open handles: `connectClient()` in `collaboration.test.ts` left a 5 s `setTimeout` running after each connect. The timer is now cleared on connect and on error, and `jest --detectOpenHandles` is clean.

**Deferred**
- Production advisories that remain (19, from 2 roots):
  - `@opentelemetry/core` < 2.8.0, which needs the OTel JS 2.x migration (`sdk-node` 0.49 → 0.2xx). That migration is breaking: `Resource` becomes `resourceFromAttributes`, and exporter and semantic-convention imports change.
  - `qs` via `express@4.22.1`, which pins `qs@~6.14`. Fixing it needs Express 5, or an `overrides` entry after checking compatibility.
- The remaining dev-only advisories come from `eslint@8` (EOL) / `@typescript-eslint@7`, Jest 29 transitives (`braces`, `@babel/*`, `handlebars`, `js-yaml`), `sprintf-js` and `esbuild` (via `tsx`). Fixing them means ESLint 9 with flat config, typescript-eslint 8, and possibly Jest 30.
- `DEPENDENCY_NOTES.md` says lodash is pinned to 4.17.20 for "legacy document transform utilities" (DEPS-301). In fact `package.json` declares `^4.18.0`, and nothing in `src/` imports lodash. Documented only, in case this is a workshop artifact. If not, remove the dependency and the note.
- `src/config.ts` falls back to `JWT_SECRET || 'otterworks-dev-secret'`, which differs from the docker-compose default. Left alone because it is auth behavior. Recommendation: fail fast when `JWT_SECRET` is unset outside development, as api-gateway does.
- `y-websocket` 1.5.x is the legacy line (2.x/3.x split the server into `@y/websocket-server`).

**Coverage gaps**
- The existing suites (`src/__tests__/`) test the Socket.IO flows. Check whether the Yjs WebSocket upgrade path in `src/index.ts` (token from query/header, `jwt.verify`) and Redis-adapter failure handling need dedicated tests.

---

## admin-service (Ruby 3.3 / Rails 7.1)

**Fixed**
- RuboCop crashed on load: `rubocop-rspec` 2.31 pulled in `rubocop-rspec_rails` 2.29.1, which calls the removed `inject_defaults!` API. I upgraded `rubocop-rspec` to `~> 3.0` (3.10.2) and moved `.rubocop.yml` from `require:` to `plugins:`. `rubocop` itself went 1.86.1 → 1.92.0.
- Security: `rails-html-sanitizer` 1.7.0 → 1.7.1 (plus `loofah` 2.25.2), `websocket-driver` 0.8.0 → 0.8.2. bundle-audit is clean.
- `rubocop -a` (safe autocorrect only) on 15 app files: hash alignment, trailing commas, `%w[]`, and a redundant `begin` inside a block. It also replaced `:unprocessable_entity` with `:unprocessable_content`, which is still HTTP 422; Rack 3.2.6 deprecates the old symbol. `ChaosController` and `ChaosProbeService` got layout-only changes; their behavior is identical.
- Specs and `bulk_controller.rb` were moved to `:unprocessable_content` the same way, which removes the Rack deprecation warnings from the spec run.

**Deferred**
- 58 RuboCop offenses remain:
  - Unsafe autocorrects: `Rails/ResponseParsedBody` ×28 in specs, `Rails/WhereRange` ×3, `Rails/Pluck`, `Rails/FindEach`, `Rails/Blank`
  - `Layout/LineLength` ×12
  - Metrics: complexity and length in a few controllers/services

  The unsafe fixes can change semantics and the Metrics ones need refactoring, so I left them for reviewed follow-ups.
- `config/secrets.yml` / `Rails.application.secrets` is deprecated and gets removed in Rails 7.2. `JwtAuthenticator#decode_token` still falls back to `secrets.jwt_secret`. Move to credentials or ENV before the Rails 7.2 upgrade.
- Rails 7.1 → 7.2/8.0 is a separate migration.
- RuboCop is not part of `make lint`; adding it is recommended now that it runs.
- `ChaosController#verify_chaos_secret` allows requests when `CHAOS_SECRET` is unset ("dev mode"). This is intentional, so it is documented only.
- The planted bug in `config/environments/production.rb` was left untouched, as `AGENTS.md` requires.

**Coverage gaps**
- Line coverage is 36.88% (426/1155, SimpleCov). Per-file coverage wasn't broken down; start with the services and webhook controllers.

---

## audit-service (C# 12 / ASP.NET 8)

**Fixed**
- `dotnet format whitespace` fixed 4 errors in `tests/AuditService.Tests/ArchiveEventsTests.cs` (line 132).
- OpenTelemetry `Exporter.OpenTelemetryProtocol` / `Extensions.Hosting` 1.7.0 and `Instrumentation.AspNetCore` 1.7.1 → 1.20.1. No code changes were needed. This clears GHSA-vh2m-22xx-q94f, GHSA-g94r-2vxg-569j and GHSA-4625-4j76-fww9, plus the transitive `System.Text.Json` 8.0.0 advisories (GHSA-hh2w-p6rv-4g7w, GHSA-8g4q-xg66-9fp4). `dotnet list package --vulnerable --include-transitive` is clean.

**Deferred: major bumps that need migration work**
- `AWSSDK.*` 3.7 → 4.x: collections now default to null and the nullable annotations change, which touches DynamoDB/S3/SQS/SNS call sites.
- `Serilog.AspNetCore` 8 → 9/10, `Npgsql` 8 → 9/10, `Microsoft.Data.SqlClient` 5.2 → 6.x: all major versions. Test them against the archive-store integrations (Db2/Postgres/Azure SQL).
- Test stack: `Microsoft.NET.Test.Sdk` 17.8, `xunit` 2.5.3 → 2.9 or v3, `coverlet` 6.0.0. Low risk; can be batched.
- The .NET 10 move is covered in the EOL table above.

**Static review**
- No hardcoded credentials. Archive-store passwords come from env (`ArchiveStoreOptions`).

**Coverage gaps**
- 53 tests pass. Coverage wasn't measured in this pass; run `coverlet` (already referenced) to find gaps in the SQS/S3/DynamoDB paths.

---

## Repo-convention consistency

| Service | Dockerfile | `docker-compose.yml` | Helm `infrastructure/helm/<svc>/` | Shared schemas |
|---|---|---|---|---|
| api-gateway | ✅ | ✅ | ✅ | No OpenAPI for gateway routes (documented) |
| search-service | ✅ | ✅ | ✅ | ✅ `shared/openapi/search-service.yaml`  |
| collab-service | ✅ | ✅ | ✅ | ✅ `shared/events/schemas/collaboration-events.json` |
| admin-service | ✅ | ✅ | ✅ | No OpenAPI for `/api/v1/admin/*` (documented) |
| audit-service | ✅ | ✅ | ✅ | ✅ `shared/events/schemas/audit-events.json`; no OpenAPI (documented) |

Adding OpenAPI specs for the gateway, admin and audit services is more than a small fix, so it
is listed as a follow-up.

## Recommended follow-ups (priority order)

1. **Go 1.25 upgrade for api-gateway**, then bump `chi`, `otel`, `x/net` and `grpc`. This clears the remaining govulncheck findings.
2. **Node 22/24 LTS for collab-service**, plus the OTel JS 2.x migration and ESLint 9 / typescript-eslint 8.
3. **.NET 10 plan for audit-service** before .NET 8 reaches end of support (November 2026), together with the AWS SDK v4 migration.
4. **admin-service**: move off `Rails.application.secrets`, then upgrade to Rails 7.2. Work through the remaining RuboCop offenses and add RuboCop to `make lint` and CI.
5. **search-service**: add `pyproject.toml` with a pinned ruff version and rules, one `ruff format` commit, and ruff in CI.
6. Fix the out-of-scope `auth-service` Gradle wrapper so the aggregate `make lint` runs to completion.
7. Add OpenAPI specs to `shared/openapi/` for the gateway, admin and audit services.
