"""
Pipeline exception hierarchy.

Every exception's *message* is written to be safe for API clients — no raw
upstream responses, stack traces, or internal paths. Anything sensitive is
logged where the error is raised, never put in the message. The API layer
maps `status_code` straight onto the HTTP response, so adding a new error
type never requires touching the routes.
"""


class PipelineError(Exception):
    """Base class — `str(exc)` is safe to return to API clients."""

    status_code = 500


class InvalidDocumentError(PipelineError):
    """The uploaded document cannot be processed (corrupt, encrypted, empty…)."""

    status_code = 422


class ConfigurationError(PipelineError):
    """A required credential/setting is missing — an operator problem."""

    status_code = 503


class UpstreamServiceError(PipelineError):
    """OpenAI / Azure failed or returned something unusable."""

    status_code = 502
