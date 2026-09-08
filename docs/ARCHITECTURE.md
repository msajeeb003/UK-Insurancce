# Architecture

Aligned to BRD v1.2 (Upload → Extraction → Review → Compare → Export).

## Extraction pipeline

```
POST /extract-quote (PDF or .xlsx upload, ≤25 MB, ≤60 pages)
        │
        ├─ .xlsx ──► backend/app/extraction/excel_extractor.py
        │            credit-limit schedules: one worksheet = one "page",
        │            rows rendered as explicit pipe-separated grids
        │
        ▼ (.pdf)
 backend/app/extraction/detector.py
   PyMuPDF text-layer probe: count extractable chars per page.
   ≥40% low-text pages → SCANNED, else DIGITAL (both tunable via .env)
        │
        ├─ DIGITAL ──► backend/app/extraction/pymupdf_extractor.py
        │              position-sorted text blocks per page
        │
        └─ SCANNED ──► backend/app/extraction/azure_extractor.py
                       Azure Document Intelligence prebuilt-layout:
                       lines + tables rebuilt as markdown grids
        │
        ▼
 backend/app/extraction/base.py
   pages joined with "=== PAGE n ===" markers — the LLM's only
   source of page numbers (this is what makes source-linking honest)
        │
        ▼
 backend/app/llm/router.py -> openai_extractor / anthropic_extractor
   Claude or OpenAI structured outputs, temperature 0, one shared prompt
   compiled from the Pydantic model in backend/app/models/schemas.py.
   The prompt's terminology section is BUILT AT REQUEST TIME from the
   mapping library (backend/config/terminology.json, BRD 2.3) and the standing
   insurer list (backend/config/insurers.json)
        │
        ▼
 backend/app/services/pipeline.py :: _sanitize + verification + review + set fields
   1) sanitize: out-of-range page cites cleared, confidence made
      consistent
   2) backend/app/services/verification.py: EVERY value is checked against the
      actual document text — verbatim match first, then per-figure digit
      runs so "GBP 12,600" matches a printed "£12,600.00". Wrong page
      cites are corrected, dropped ones recovered, and a value found
      NOWHERE is downgraded to 'uncertain' + listed in
      review.unverified_fields (anti-hallucination: a wrong number that
      looks plausible must never reach the broker as certain)
   3) review summary + debt collection SET by the insurer rule (BRD 2.4)
   — none of this is asked of the LLM
        │
        ▼
 ExtractionResponse JSON (meta + review + set_fields + data)
```

## Configuration, not code (BRD 2.4)

`backend/config/insurers.json` (standing list, aliases, debt-collection rule) and
`backend/config/terminology.json` (the client-compiled mapping library) are re-read
whenever the file changes on disk — adding an insurer, moving one between
Included and Outsourced, or extending the terminology never requires a
release or even a restart. `GET /insurers` serves the list to the frontend.

## Design decisions

- **Never guess** (BRD 2.2) — every scalar is `{value, page, confidence}`; a
  missing value is `{null, null, null}`. "N/A" and "Fixed" are broker
  entries, never extraction output. The schema makes placeholders
  indistinguishable from data, so the prompt forbids them and nullable types
  enforce it.
- **Set beats guessed** (BRD 2.4) — type of policy (broker, at setup) and
  debt collection support (insurer rule) are structurally absent from the
  LLM schema; the model cannot return them. The rule result travels in
  `set_fields`, clearly separated from extracted data, and stays editable.
- **The 16-field list is definitive** (BRD 2.3) — countries covered,
  exclusions and special conditions are not comparison rows; material notes
  of that kind flow into `additional_info` (per the BRD open item) until
  the client confirms otherwise.
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
