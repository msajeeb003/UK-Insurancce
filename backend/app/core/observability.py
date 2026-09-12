"""
Observability, kept light: JSON logs with a request id, PII/secret scrubbing,
a single alert channel, an optional Sentry hookup, and small health/disk
helpers. No heavy infra — everything degrades to a no-op when unconfigured.
"""

import json
import logging
import re
import shutil
import time
import urllib.request
import uuid
from contextvars import ContextVar

from app.core.config import get_settings

logger = logging.getLogger("app")

# Per-request correlation id, attached to every log line for that request.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
user_id_var: ContextVar[str] = ContextVar("user_id", default="-")


# ── PII / secret scrubbing ─────────────────────────────────────────────────
# Never let document contents, buyer names, keys or tokens reach logs/Sentry.
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{6,}|Bearer\s+\S+|eyJ[\w\-]+\.[\w\-]+\.[\w\-]+)", re.I
)
_SENSITIVE_KEYS = re.compile(
    r"(password|secret|token|api[_-]?key|authorization|cookie|csrf)", re.I
)


def scrub_text(text: str) -> str:
    return _SECRET_RE.sub("[redacted]", text) if text else text


def scrub_data(obj):
    """Recursively redact sensitive keys/values; drop obviously large blobs
    (document text) so PII/quote contents never leave the process."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _SENSITIVE_KEYS.search(str(k)):
                out[k] = "[redacted]"
            else:
                out[k] = scrub_data(v)
        return out
    if isinstance(obj, list):
        return [scrub_data(v) for v in obj]
    if isinstance(obj, str):
        if len(obj) > 500:            # a long string is likely document text
            return f"[omitted:{len(obj)} chars]"
        return scrub_text(obj)
    return obj


# ── JSON logging ───────────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": scrub_text(record.getMessage()),
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
        }
        # structured extras (project_id, duration_ms, event, …)
        for key, val in getattr(record, "extra_fields", {}).items():
            payload[key] = val
        if record.exc_info:
            payload["exc"] = scrub_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def log_event(event: str, **fields) -> None:
    """Emit one structured event line (timings, metrics, hot-path markers)."""
    logger.info(event, extra={"extra_fields": {"event": event, **fields}})


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


# ── Alerting (one channel; degrades to an ERROR log) ────────────────────────

def alert(message: str) -> None:
    logger.error("ALERT: %s", scrub_text(message))
    url = get_settings().backup_alert_webhook  # reuse the one configured channel
    if url:
        try:
            req = urllib.request.Request(  # noqa: S310 — operator-configured https webhook
                url, data=json.dumps({"text": scrub_text(message)}).encode(),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            urllib.request.urlopen(req, timeout=10)  # noqa: S310
        except Exception:
            logger.exception("Failed to send alert webhook")


# ── Disk headroom (alert when the volume is near full) ──────────────────────

def disk_free_ratio() -> float:
    try:
        usage = shutil.disk_usage(get_settings().data_path)
        return usage.free / usage.total if usage.total else 1.0
    except Exception:
        return 1.0  # a health check must never crash on an odd path


# ── Sentry (optional; DSN-gated) ────────────────────────────────────────────

def _sentry_before_send(event, hint):
    """Strip request bodies/headers and redact secrets before an event leaves."""
    req = event.get("request")
    if isinstance(req, dict):
        req.pop("data", None)          # request body may hold buyer names / doc text
        req.pop("cookies", None)
        if isinstance(req.get("headers"), dict):
            req["headers"] = {k: ("[redacted]" if _SENSITIVE_KEYS.search(k) else v)
                              for k, v in req["headers"].items()}
    if "extra" in event:
        event["extra"] = scrub_data(event["extra"])
    return event


def init_sentry() -> bool:
    """Initialise Sentry if SENTRY_DSN is set. Returns whether it started."""
    dsn = get_settings().sentry_dsn
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN set but sentry-sdk not installed")
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=get_settings().sentry_environment,
        send_default_pii=False,        # no cookies/headers/body by default
        traces_sample_rate=0.0,        # errors only; no perf tracing infra
        before_send=_sentry_before_send,
    )
    return True


def capture(exc: BaseException, **context) -> None:
    """Send an exception to Sentry if active (scrubbed); always safe to call."""
    try:
        import sentry_sdk
        if sentry_sdk.Hub.current.client:
            with sentry_sdk.push_scope() as scope:
                for k, v in scrub_data(context).items():
                    scope.set_extra(k, v)
                sentry_sdk.capture_exception(exc)
    except Exception:
        logger.debug("Sentry capture skipped", exc_info=True)
