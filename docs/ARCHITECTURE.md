# Architecture

## Extraction pipeline

```
POST /extract-quote (PDF upload, ≤25 MB, ≤60 pages)
        │
        ▼
 app/extraction/detector.py
   PyMuPDF text-layer probe: count extractable chars per page.
   ≥40% low-text pages → SCANNED, else DIGITAL (both tunable via .env)
        │
        ├─ DIGITAL ──► app/extraction/pymupdf_extractor.py
        │              position-sorted text blocks per page
        │
        └─ SCANNED ──► app/extraction/azure_extractor.py
                       Azure Document Intelligence prebuilt-layout:
                       lines + tables rebuilt as markdown grids
        │
        ▼
 app/extraction/base.py
   pages joined with "=== PAGE n ===" markers — the LLM's only
   source of page numbers (this is what makes source-linking honest)
        │
        ▼
 app/llm/openai_extractor.py
   OpenAI Responses API, temperature 0, strict Structured Outputs
   compiled from the Pydantic model in app/models/schemas.py
        │
        ▼
 app/services/pipeline.py :: _sanitize + _build_review
   hallucinated / out-of-range page citations cleared (values kept),
   confidence flags made consistent, then missing/uncertain fields
   summarized deterministically — never by the LLM
        │
        ▼
 ExtractionResponse JSON (meta + review + data)
```

## Design decisions

- **Never guess** — every scalar is `{value, page, confidence}`; a missing
  value is `{null, null, null}`. The schema makes placeholders
  indistinguishable from data, so the prompt forbids them and nullable types
  enforce it.
- **Uncertainty is surfaced, not hidden** — the LLM marks shaky values
  `confidence: "uncertain"`; the server then computes the `review` block
  (missing + uncertain field lists) deterministically, and the UI shows an
  amber highlight with a `?` chip. A broker editing a cell counts as human
  verification and clears the flag.
- **Ignored fields** ("Type of policy", "Debt collection support") are absent
  from the schema itself — the model *cannot* return them.
- **`excess_type` is never normalized** — the insurer's original wording is a
  business requirement.
- **Error contract** (`app/core/errors.py`): pipeline code raises
  `PipelineError` subclasses whose messages are client-safe and carry an HTTP
  status. The route maps them 1:1; every other exception is an opaque 502
  with details only in server logs.
- **Blocking SDK calls** (Azure poller, OpenAI) run in worker threads via
  `asyncio.to_thread`, keeping the event loop responsive.
- **Secrets** are `pydantic.SecretStr` — they cannot leak via repr/logging.
- The pipeline module has **no FastAPI imports**, so it can be reused by a
  batch worker or tested without the web layer.

## Frontend

`frontend/` is a dependency-free vanilla SPA (state machine + render
functions) implementing the approved wireframe 1:1. It talks to the backend
only through `POST /extract-quote`. Projects persist in `localStorage`;
sign-in is a stub until real auth lands. Every dynamic value is HTML-escaped
before insertion (`esc()`), so extracted PDF content cannot inject markup.

## Trust boundaries

| Input | Treated as |
|---|---|
| Uploaded PDF bytes | Untrusted — validated by PyMuPDF, size/page capped |
| LLM output | Untrusted-ish — schema-constrained, page cites re-validated |
| Extracted values in the UI | Untrusted — always HTML-escaped |
| `.env` | Trusted operator input, never committed |
