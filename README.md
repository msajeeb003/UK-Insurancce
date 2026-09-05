# Insurance Quote Comparison Tool

Backend pipeline that turns insurer quote PDFs / credit limit schedules into
normalized, source-linked structured JSON — plus a wireframe-faithful frontend
(served at `/`) covering the full broker flow: Login → Projects → Setup →
Upload → Review & edit → Buyer credit limits → Recommendation → Generate &
export.

## Pipeline

```
POST /extract-quote (PDF upload)
        │
        ▼
 PyMuPDF text-layer probe ──► digital?  ──► PyMuPDF block extraction (positions kept)
        │                                        │
        └──► scanned / forced ──► Azure AI Document Intelligence (prebuilt-layout,
                                  lines + tables rebuilt as markdown grids)
                                                 │
        ┌────────────────────────────────────────┘
        ▼
 Page-tagged text ("=== PAGE n ===" markers)
        ▼
 OpenAI Responses API — Structured Outputs (strict Pydantic schema)
        ▼
 Page-link sanity pass ──► ExtractionResponse JSON
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # then fill in OPENAI_API_KEY, AZURE_ENDPOINT, AZURE_KEY
uvicorn app.main:app --reload
```

Interactive docs at http://127.0.0.1:8000/docs — upload a PDF straight from
the browser for pilot testing.

## Try it

```bash
curl -X POST "http://127.0.0.1:8000/extract-quote" -F "file=@quote.pdf"
```

Force an engine (e.g. a digital PDF whose credit-limit table extracts badly):

```bash
curl -X POST "http://127.0.0.1:8000/extract-quote?engine=azure" -F "file=@schedule.pdf"
```

## Response shape (abridged)

```json
{
  "meta": {
    "filename": "quote.pdf",
    "page_count": 4,
    "extraction_engine": "pymupdf",
    "llm_model": "gpt-4o-2024-08-06"
  },
  "data": {
    "insurer": { "value": "Atradius", "page": 1 },
    "excess": { "value": "£5,000", "page": 2 },
    "excess_type": { "value": "Each and Every Loss", "page": 2 },
    "minimum_annual_premium": { "value": null, "page": null },
    "buyer_credit_limits": [
      {
        "buyer_name": "Example Ltd",
        "company_number": "01234567",
        "limit_required": "£250,000",
        "limit_offered": "£200,000",
        "page": 3
      }
    ]
  }
}
```

## Extraction rules encoded in the pipeline

1. **No guessing** — a field absent from the document comes back
   `{"value": null, "page": null}`; the schema plus prompt forbid placeholders.
2. **Source linking** — every value carries the 1-based PDF page it came
   from; out-of-range page citations are stripped by a post-validation pass.
3. **Normalization** — insurer synonyms (Deductible / Minimum Retention /
   Excess, MAL / Maximum Aggregate Liability, …) map to standard fields,
   **except** `excess_type`, which keeps the insurer's original wording.
4. **Ignored fields** — "Type of policy" and "Debt collection support" are
   deliberately absent from the schema (set by broker rules downstream).

## Module map

| File | Responsibility |
|---|---|
| [app/main.py](app/main.py) | FastAPI app, upload validation, error mapping |
| [app/pipeline.py](app/pipeline.py) | Orchestration + page-link sanity pass |
| [app/config.py](app/config.py) | Env/`.env` settings (keys, thresholds) |
| [app/schemas.py](app/schemas.py) | Pydantic models incl. the strict LLM schema |
| [app/extraction/detector.py](app/extraction/detector.py) | Digital vs scanned classification |
| [app/extraction/pymupdf_extractor.py](app/extraction/pymupdf_extractor.py) | Digital PDF text (position-ordered blocks) |
| [app/extraction/azure_extractor.py](app/extraction/azure_extractor.py) | Azure DI OCR + table reconstruction |
| [app/llm/openai_extractor.py](app/llm/openai_extractor.py) | Responses API call with Structured Outputs |
| [static/index.html](static/index.html) | Frontend shell (fonts + app mount) |
| [static/styles.css](static/styles.css) | Theme tokens copied from the approved wireframe |
| [static/app.js](static/app.js) | All 8 screens, state, and `/extract-quote` wiring |

## Frontend (wireframe implementation)

Open http://127.0.0.1:8000/ after starting the server. Theme and behavior
follow `Quote Comparison Tool Wireframes.html` 1:1 — indigo `#4f46e5` accent,
Plus Jakarta Sans / IBM Plex Mono, purple SET/RULE field tags, amber
confirm-before-export gating, recommended-column highlight.

- **Upload** posts each PDF to the real `/extract-quote` endpoint; a new
  comparison column appears per extracted quote (named from the extracted
  insurer), and `buyer_credit_limits` rows merge into the Credit limits grid.
  Failures show the wireframe's amber **Unreadable** pill with the reason.
- **Source links**: every extracted cell shows its `p<n>` page chip from the
  backend's source-linking; clicking opens the source modal. Editing a cell's
  value clears its page link (it no longer matches the document verbatim).
- **Export gate**: PowerPoint/PDF buttons stay disabled until Est. premium,
  indemnity, excess and max liability are confirmed on Review. "Download PDF"
  prints the presentation preview; server-side PPTX generation is the next
  backend module.
- Projects persist in browser `localStorage`; sign-in is a front-end stub
  until real auth is added.

## Pilot notes (6 insurer formats)

- Start every new format with `engine=auto`; if a credit-limit table comes
  back misaligned, retry with `engine=azure` — DI rebuilds tables as grids.
- `meta.extraction_engine` tells you which path ran, so you can log
  per-insurer routing during the pilot.
- Tune `DIGITAL_MIN_CHARS_PER_PAGE` / `SCANNED_PAGE_RATIO` in `.env` if a
  mostly-scanned format with a digital cover page is misrouted.
