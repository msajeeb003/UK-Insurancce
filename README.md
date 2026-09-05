# Insurance Quote Comparison Tool

Internal tool for a UK credit-insurance brokerage: upload insurer quote PDFs,
review AI-extracted terms side by side, pick a recommendation, and generate a
client presentation.

- **Backend** — FastAPI pipeline: PyMuPDF (digital PDFs) / Azure Document
  Intelligence (scanned PDFs) → OpenAI Structured Outputs → normalized,
  source-linked JSON. Every value carries the PDF page it came from; missing
  values stay `null` — the system never guesses.
- **Frontend** — wireframe-faithful broker flow served at `/`:
  Login → Projects → Setup → Upload → Review & edit → Buyer credit limits →
  Recommendation → Generate & export.

## Repository layout

```
├── app/                    FastAPI backend
│   ├── main.py             App entrypoint: wiring, middleware, frontend mount
│   ├── api/routes.py       HTTP endpoints (/extract-quote, /health)
│   ├── core/
│   │   ├── config.py       Settings from .env (keys, thresholds, limits)
│   │   └── errors.py       Client-safe exception hierarchy → HTTP statuses
│   ├── models/schemas.py   Pydantic models (strict LLM schema + API responses)
│   ├── services/pipeline.py  Orchestrator: detect → extract → LLM → sanitize
│   ├── extraction/         PDF → page-tagged text
│   │   ├── detector.py     Digital-vs-scanned classification
│   │   ├── pymupdf_extractor.py   Digital PDFs (position-ordered blocks)
│   │   ├── azure_extractor.py     Scanned PDFs (OCR + table grids)
│   │   └── base.py         Shared PageText type + page markers
│   └── llm/openai_extractor.py    OpenAI Responses API call
├── frontend/               Vanilla SPA (index.html, app.js, styles.css)
├── tests/                  Pytest suite — no network, no API keys needed
├── docs/ARCHITECTURE.md    Pipeline diagram, design decisions, trust boundaries
├── .github/workflows/ci.yml  Lint (ruff) + tests on every push
├── requirements.txt        Pinned runtime dependencies
└── requirements-dev.txt    + pytest, httpx, ruff
```

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/mac: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # fill in OPENAI_API_KEY, AZURE_ENDPOINT, AZURE_KEY
uvicorn app.main:app --reload
```

- App: http://127.0.0.1:8000/
- API docs (Swagger): http://127.0.0.1:8000/docs
- Health/config check: http://127.0.0.1:8000/health

## API

```bash
curl -X POST "http://127.0.0.1:8000/extract-quote" -F "file=@quote.pdf"
```

Optional `?engine=digital|azure` forces an extraction engine (default `auto`
detects digital vs scanned). Response (abridged):

```json
{
  "meta": { "filename": "quote.pdf", "page_count": 4,
            "extraction_engine": "pymupdf", "llm_model": "gpt-4o-2024-08-06" },
  "data": {
    "insurer":  { "value": "Atradius", "page": 1 },
    "excess":   { "value": "£5,000",   "page": 2 },
    "excess_type": { "value": "Each and Every Loss", "page": 2 },
    "minimum_annual_premium": { "value": null, "page": null },
    "buyer_credit_limits": [
      { "buyer_name": "Example Ltd", "company_number": "01234567",
        "limit_required": "£250,000", "limit_offered": "£200,000", "page": 3 }
    ]
  }
}
```

## Extraction rules

1. **No guessing** — absent fields return `{"value": null, "page": null}`.
2. **Source linking** — every value carries its 1-based PDF page; out-of-range
   citations are stripped by a post-validation pass.
3. **Normalization** — insurer synonyms (Deductible / Minimum Retention /
   Excess, MAL, MTP/MEP, DL…) map onto standard fields, **except**
   `excess_type`, which keeps the insurer's original wording.
4. **Ignored fields** — "Type of policy" and "Debt collection support" are set
   by broker rules and are absent from the extraction schema entirely.

## Development

```bash
pip install -r requirements-dev.txt
pytest        # 16 tests, no API keys or network needed
ruff check .  # lint (style, imports, bugbear, security rules)
```

CI runs both on every push (`.github/workflows/ci.yml`).

## Security notes

- Secrets live only in `.env` (gitignored); settings use `SecretStr` so keys
  can't leak into logs or errors. `/health` reports *whether* keys are set,
  never their values.
- Uploads are capped (25 MB, 60 pages, PDF only) and read in size-checked
  chunks; error responses never expose internals.
- The frontend HTML-escapes all extracted content before rendering.
- Not yet implemented (pilot scope): real authentication, rate limiting,
  server-side project storage. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
