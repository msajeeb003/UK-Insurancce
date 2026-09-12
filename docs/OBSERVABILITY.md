# Observability

Light-touch: no metrics server or log pipeline to run. Everything degrades to
a no-op when unconfigured, and no PII/secrets leave the process.

## 1. Error tracking (Sentry)

- **Backend:** set `SENTRY_DSN` (and `SENTRY_ENVIRONMENT`). Unhandled
  exceptions, failed extractions and failed exports are captured via
  `observability.capture()`; a `before_send` hook strips request bodies,
  cookies and sensitive headers, and redacts key/token patterns. Errors only
  (no performance tracing infra: `traces_sample_rate=0`).
- **Frontend:** the vanilla-JS app has **no third-party SDK** (keeps the strict
  `script-src 'self'` CSP intact). `window.onerror` /
  `unhandledrejection` are reported **same-origin** to `POST /client-error`;
  the backend scrubs and forwards to Sentry. So one DSN covers both tiers.
- **Verify (forced error, PII scrubbed):**
  ```bash
  curl -X POST https://<app>/client-error -H 'Content-Type: application/json' \
    -d '{"kind":"error","message":"forced test sk-proj-SECRET123","where":"/review"}'
  ```
  The event appears in Sentry with `sk-proj-SECRET123` shown as `[redacted]`.
  (An unhandled server exception is captured automatically and returned to the
  client as a clean `500 {"detail":"Internal error."}`.)

## 2. Structured logging

JSON to stdout (Railway captures it). Every line carries `request_id` (also
returned as the `X-Request-Id` response header) and `user_id`. Hot paths emit
timed events:

- `extraction` — engine, pages, `duration_ms` (upload→extraction).
- `generation` — format, columns, `duration_ms`.
- `extraction_failed`, `client_error`, plus a `5xx` marker.

Messages are scrubbed and long strings (likely document text) are omitted, so
client financials / buyer names / keys never land in logs. Client-facing error
messages stay generic; detail lives server-side.

## 3. Health & readiness

- `GET /healthz` — shallow: process is up (`{"status":"ok"}`). Point the
  uptime monitor here.
- `GET /readyz` — deep: DB writable, `DATA_DIR` writable, an LLM provider
  configured, and disk headroom. Returns **503** if any dependency is broken
  (e.g. the volume is unwritable), with a per-check breakdown.

## 4. Uptime & alerting

- **Uptime monitor** (UptimeRobot / Better Stack / etc.): check `GET /healthz`
  every 1–5 min, plus a **synthetic login check** (`POST /auth/login` with a
  dedicated monitoring account, expect 200). Alert on downtime.
- **Alert channel:** set `BACKUP_ALERT_WEBHOOK` (Slack/email-in webhook). It
  fires on **backup failure, integrity-check failure, and disk near full**
  (`/readyz` alerts when free disk < `DISK_FREE_MIN_RATIO`). All alerts also
  log at ERROR (surfaced by Railway).
- **Error-rate spikes:** configure a Sentry alert rule on event volume.
- **Verify (simulated backup failure):** run a backup with a bad offsite
  target (e.g. unreachable bucket) → `python -m app.backup run` → an ERROR
  `BACKUP ALERT:` log line and a webhook POST fire.

## 5. Metrics (BRD §5 success measures)

Recorded per generation in the `metrics` table (no external store):

- `GET /metrics` — JSON aggregates (auth required).
- `GET /metrics/view` — a minimal internal HTML dashboard (auth required).

Shows: **average preparation time** (project creation → export), **average
generation time**, **field edit rate** — of the non-set fields the AI actually
extracted, the share the broker changed; the two set fields
(`type_of_policy`, `debt_collection_support`) are excluded because they are not
extraction attempts — and **exported-without-rebuild**. Numbers accrue as
brokers use the tool.
