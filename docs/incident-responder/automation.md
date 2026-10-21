# Incident responder — the Automation that answers the page

This is the configuration of the Devin Automation that turns a firing alert into
a Devin session with no human prompt in between. It is written for the
document-service incident demo (`incident/scenarios.yaml`,
`.workshop/playbooks/incident-responder.devin.md`,
`.agents/skills/incident-responder/SKILL.md`) but nothing in it is specific to
the N+1 scenario: the same automation answers all four alerts on `main`.

Register it in the **Demo org** (the org the sessions must appear in), never in
the internal org: Settings → Automations, or the v3 API
`POST /v3/organizations/{org_id}/automations`. Register the Playbook first so the
`!incident_responder` macro in the prompt resolves.

## Trigger

| Field | Value | Why |
|---|---|---|
| Event | `webhook:incoming` | Alertmanager already speaks webhooks; nothing new to deploy and nothing that can be typed by a human. |
| Payload | Alertmanager v4 webhook JSON (`observability/alertmanager/alertmanager.yml.tmpl`, receiver `devin`) | The body is appended verbatim to the prompt, so the session reads the exact alert the on-call saw. |
| Conditions | Alertmanager only routes `page: devin` alerts to this receiver, and only `status: firing` (`send_resolved: false`) | Resolved notifications and diagnostic alerts (`DocumentListQueryFanout`) must not start sessions. Filtering at the router keeps the automation itself unconditional and auditable. |
| Higher-fidelity variant | `slack:message` on the alert channel (real channel ID such as `C0123ABC456`), condition: message posted by the Alertmanager Slack app | The session is then bound to the alert's Slack thread (`attach_thread`), so the RCA lands where the on-call is already reading. Use it when a Slack channel is available; the webhook trigger stays as the fallback. |

Time-to-fire is a property of the alert rule, not the automation:
`DocumentListLatencyHigh` pages within 180 s of `make arm SCENARIO=n-plus-one`
(measured ≈ 87–90 s), see `incident/scenarios.yaml` → `alert.fires_within_seconds`
per scenario.

## Action

`start_session` with the prompt below. The session's repository is
`Cognition-Partner-Workshops/otterworks`; its `incident-responder` Skill is
auto-loaded, so the prompt carries the *order of work*, not the commands.

```text
!incident_responder

You have been paged. The Alertmanager webhook payload for the firing alert is appended below; it is the whole brief, and nobody will type a follow-up prompt. The paging service lives in @Cognition-Partner-Workshops/otterworks (the document-service; its `incident-responder` Skill is auto-loaded and has every command you need).

If the payload's top-level `status` is `resolved` (Alertmanager also notifies on resolve), do nothing: reply with one line naming the alert and its `endsAt`, and stop.

Work in this order and do not skip a step:
1. Read the payload: alert name, `service`, `scenario`, `severity`, the summary's metric and threshold, `startsAt`, and the `dashboard_url` / `traces_url` / `runbook_url` annotations. If the payload contains a Slack channel and message timestamp, that thread is where your RCA goes; otherwise the RCA goes in the PR description and your final message.
2. Telemetry before code. Open the dashboard and trace links from the annotations and write down three facts with numbers: the user-facing symptom (p95, error ratio, memory, duplicate windows), what is NOT changing (request rate flat, no deploy), and what the traces say the time or resource is spent on. If those hosts are unreachable from your machine, say so and get the same numbers from your local reproduction in step 3 instead.
3. Reproduce on your own machine on the code the paging tenant actually runs: the alert's `branch` label names the branch that tenant deploys (`git fetch origin <branch> && git checkout <branch>`); `main` is right only if the label says `main`, the `namespace` is `otterworks-main`, or the payload names no tenant namespace at all. Never derive the branch from the namespace — if the payload has a tenant namespace but no `branch` label, stop and report that instead of guessing. Then run `make incident-up UI=1`, then `make incident-arm SCENARIO=<scenario from the payload>` and `make incident-verify SCENARIO=<scenario> EXPECT=before`. The gate must go green (the alert fires locally and the before-thresholds are met) before you touch code. Open the local Grafana (http://localhost:3001, admin/otterworks) and Jaeger (http://localhost:16686) and capture the flat-traffic/rising-latency panel and the one trace that fans out — those two screenshots go in the PR. For `n-plus-one`, also sign in to http://localhost:3000 as `oncall@otterworks.dev` / `OnCall-Demo-1` and screen-record http://localhost:3000/documents loading slowly with DevTools → Network showing the request's time and `x-db-queries` header.
4. Find the cause in code by following the span names and SQL text back to the function that emits them; check `git log -S` for when it arrived. Name the file, function and line.
5. Make the smallest fix that removes the cause: a query change, a migration if an index is missing (a new Alembic revision; never edit an existing one), and one regression test that pins the property the alert measured. No refactors, no changes to alert rules, thresholds, `incident/scenarios.yaml`, `incident/expected.yaml`, seeds or dashboards. Run the service's lint (`ruff`) and its focused tests.
6. Prove it with the same load: rebuild (`make incident-up`), run `make incident-verify SCENARIO=<scenario> EXPECT=after`, and record the before/after numbers side by side from the gate output (for n-plus-one that is p95 and SQL statements per request; for the others, the metric named in the alert). The alert must be inactive under the same load. For `n-plus-one`, record the same browser page again while the scenario is still armed, now fast. If the gate is red, the fix is not done — read the trace for the new build and iterate; never edit the gate.
7. Open one PR from a new branch `devin/<unix-timestamp>-<alert-slug>`. Its base is the alert's `fix_branch` label when the payload carries one — that is the long-lived tenant branch whose tenant takes the fix (the paging tenant keeps running the flawed code until a human merges and promotes it), so `git fetch origin <fix_branch>` and branch from it; the diff is the same because that branch tracks the one you reproduced on. Without a `fix_branch` label, the base is the branch you checked out in step 3 (the alert's `branch` label; `main` only in the cases above). Never open the PR against `main` when a `fix_branch` is present. The body has: what users saw, what telemetry showed, the root cause (file:function:line), the fix in one sentence, the before/after table, the two screenshots, the before/after browser recording (embed its file path so it uploads), and the exact gate commands you ran with their output. Keep the diff to the query change, the migration, the test and (if needed) the model/service code the query touches.
8. Post the RCA: one message in the alert's Slack thread if you have one (users saw / telemetry showed / root cause / fix / before-after / PR link), otherwise as your final message. Run `make incident-disarm` before you finish.

Never push to any branch other than your own, never merge, and never silence the alert (rule edits, threshold changes, inhibitions) as a fix. If you cannot reproduce the alert locally, stop and report exactly what you saw instead of guessing at a fix.
```

Why each instruction is there, in one line each:

- **Trace first** — the differentiator is that Devin investigates like an SRE, not that it greps; the numbers it writes down become the RCA.
- **Branch from the alert's `branch` label, never from the namespace** — `workshop-<id>` and `demo-<id>` share a tenant id and a tenant can track `main`, so a namespace-derived guess can land the PR on the wrong base. Where the label comes from: `scripts/deploy-tenant.sh --branch <branch>` (the branch the ops dashboard recorded at check-out, passed by `demo-platform/runner/entrypoint.sh`) sets `monitoring.rules.extraLabels.branch` on the document-service chart, and the chart's `PrometheusRule` merges `extraLabels` into every tenant alert. The local Compose alerts (`observability/prometheus/incident_alerts.yml`) carry no `namespace` label and the golden tenant is `otterworks-main`; both mean `main`. A tenant namespace with no label means the tenant was deployed outside that path, and the responder stops rather than guessing.
- **`fix_branch` picks the PR base** — the perpetual `t-main` tenant is where the page fires (`infrastructure/helm/tenant-values/main/document-service.yaml` turns its rules on and stamps `fix_branch: demo-incident`), but `main` is the golden app and its planted flaws stay planted, so the fix goes to the long-lived `demo-incident` branch and CD ships it to `otterworks-incident`. The label carries that decision so the prompt never hard-codes a branch name; `incident/tenant.sh arm main` is the only sanctioned way to make t-main page (fixture + load, no flags, no code).
- **Reproduce with the before gate** — a green `EXPECT=before` is the proof that the machine sees the same incident the alert saw; no fix before that.
- **Smallest fix, named shape** — "query change, migration, test" is what a reviewer will merge in a minute; refactors are how a first responder makes an incident worse.
- **Prove with the same load** — `EXPECT=after` drives the identical load profile and refuses an unchanged source fingerprint, so the before/after numbers are comparable and cannot come from idling.
- **Browser recording before and after** — the gates convince a machine; a reviewer believes the page they can watch go from slow to fast under the same load. It is also the only browser-level check in the workshop flow.
- **No edits to rules, thresholds, scenarios, evidence** — the only way to silence a page is to remove its cause.
- **Slack thread if present, PR body otherwise** — the RCA goes where the on-call is reading, and the flow still completes without Slack.
- **Disarm before finishing** — the harness is left ready for the next run.

## Connectors

| Connector | Setting | Why |
|---|---|---|
| Repository | `Cognition-Partner-Workshops/otterworks` | The Skill, harness, Compose stack and code are all in it; a session that cannot clone it fails in its first minute. |
| Observability MCP | none by default | The local Prometheus/Grafana/Jaeger fallback is the default; the session gets telemetry from the alert annotations and its own reproduction. Adding a Grafana, Datadog or Sentry MCP connector is the upgrade path for a real tenant and needs no prompt change (step 2 already says "open the dashboard and trace links"). |
| Slack | the alert channel (`#otterworks-alerts`, real channel ID) | Only needed for the thread reply in step 8 and for the `slack:message` trigger variant. |
| GitHub | via the org's GitHub app | For the PR in step 7. |

## Budget and limits

| Setting | Value | Why |
|---|---|---|
| Agent mode | Normal | The Skill carries the mechanics; Normal completes the loop and is the cost-efficient default for unattended runs. |
| ACU limit | 15 per session | A clean run of reproduce → fix → prove is well under this; the cap bounds a runaway iteration on a red gate. |
| Invocation cap | 3 per 3600 s | Alertmanager re-notifies every `repeat_interval`; the cap stops a stuck alert from starting a session an hour, and 3 covers a demo re-run plus one fallback. |
| Concurrency | 1 running, queue depth 0 | Two responders on one page collide on the same branch prefix and the same tenant; the second page is dropped, not queued, because a queued run would start after the incident is over. |
| Approval | `bypass_approval: false` | Unattended does not mean unaccountable; the session appears in the org's session list under the automation and can be stopped there. Set `true` only if the triggered session must itself spawn children. |

## Network policy

Allowlisted hosts, in the order the session needs them:

| Hosts | Why |
|---|---|
| `git-manager.devin.ai`, `github.com`, `api.github.com`, `*.githubusercontent.com` | Clone, push, open the PR. |
| `registry-1.docker.io`, `auth.docker.io`, `index.docker.io`, `hub.docker.com`, `*.docker.com`, `*.docker.io`, `ghcr.io`, `*.pkg.github.com`, `quay.io`, `*.quay.io` | Images for the Compose stack (Postgres, Redis, Prometheus, Grafana, Jaeger, Alertmanager, OTel collector). |
| `pypi.org`, `files.pythonhosted.org`, `astral.sh`, `*.astral.sh` | `poetry install`, `uv`/`uvx ruff` for the document-service and the harness. |
| `deb.debian.org`, `*.debian.org`, `archive.ubuntu.com`, `security.ubuntu.com` | Base-image package installs during the document-service build. |
| `*.otterworks.app` | The tenant, dashboards and traces named in the alert annotations when the incident is on the shared cluster. |

Everything else is denied. Slack and the Devin API are reached through the
platform's own integrations, not the session's network.

**Known limitation (2026-09):** on the partner-workshops enterprise host, a
session started with this `net_policy` gets `403 Forbidden` from
`git-manager.devin.ai` on every fetch and push even though the host is
allowlisted, so the responder can diagnose and fix but cannot open the PR. The
same prompt with `net_policy` omitted fetches and pushes normally (verified
with a pair of otherwise identical throwaway automations). Until the platform
fix lands, the registered Automation runs with `session_settings.net_policy`
omitted and relies on the ACU cap, invocation cap and `bypass_approval: false`
for containment; re-add the allowlist above once a policy-scoped session can
reach the git proxy.

## Wiring Alertmanager to it

For the local Compose stack, set `DEVIN_WEBHOOK_URL` to the Automation's
incoming-webhook URL and `DEVIN_WEBHOOK_SECRET` to its one-time secret (sent
as `X-Webhook-Secret`); `observability/alertmanager/entrypoint.sh` renders both
into `alertmanager.yml.tmpl`. With neither set the flow runs with no
credentials: the page is delivered only to the local sink
(`http://alert-sink:9095/devin`). When they are set the page is delivered to
the Automation *and* mirrored to the sink, so `make incident-verify
SCENARIO=<s> EXPECT=before` and `make incident-simulate` keep working in real
mode. The shared cluster's Alertmanager (the
`platform-engineering-shared-services` repo, same receiver name) posts to the
Automation directly. Set `SLACK_WEBHOOK_URL` alongside it to post the same
alert into the channel.

On the shared cluster the header must be declared as
`http_headers.X-Webhook-Secret.values`, not `.secrets`: prometheus-operator
re-marshals the Alertmanager config and writes every Secret-typed field back as
the literal string `<secret>`, so a `secrets:` entry reaches the Automation as
`X-Webhook-Secret: <secret>` and every page is rejected with
`403 {"detail":"Invalid webhook secret"}` even though the Kubernetes Secret
holds the right value. (The whole config file already lives in a Kubernetes
Secret, so nothing is lost.) The local Compose stack runs Alertmanager without
the operator and is unaffected.

`make incident-simulate RECEIVER=devin` prints the exact JSON the automation
received on the last page; it is the payload to paste into a session by hand if
the automation is ever unavailable during a demo.

## Validated configuration

The payload below validated against the Automations API (`validate_create`) and
is the record replicated in the Demo org. `session_settings.net_policy` is
omitted while the git-proxy limitation above stands; the allowlist it would
carry is the table under *Network policy* (the registration helper re-adds it
with `INCIDENT_NET_POLICY=1`):

```json
{
  "name": "OtterWorks incident responder — Alertmanager page → Devin first response",
  "run_as": {"type": "organization"},
  "triggers": [{"event_type": "webhook:incoming"}],
  "actions": [{
    "type": "start_session",
    "prompt": "<the prompt above>",
    "session": {"tags": [], "bypass_approval": false}
  }],
  "limits": {
    "max_acu_limit": 15,
    "invocations": {"max_per_window": 3, "window_seconds": 3600}
  },
  "concurrency": {"max_concurrent_runs": 1, "max_queue_depth": 0},
  "session_settings": {"devin_mode": "normal"},
  "tools": {"mcp_servers": [], "slack_channels": [{"team_id": "*", "channel_id": "*"}]},
  "metadata": {"demo": "incident-responder", "service": "otterworks-document-service"},
  "enabled": true
}
```
