# LLM data processing — no training, controlled retention

The tool sends confidential client/insurer/buyer text to an LLM provider for
extraction. This documents — and the code enforces — that the data is **not
used for training** and how retention is controlled.

## What is sent (minimisation)

For each extraction the payload is only:

- **the document's extracted text**, page-tagged (`=== PAGE n ===`), fenced
  as untrusted data; and
- **the static system prompt** — extraction rules plus the client-maintained
  terminology library and standing insurer list (configuration, not
  per-request data).

Nothing else is sent: **no filename, no user id, no project id, no session or
account data.** The document text is the minimum necessary input — extraction
cannot happen without it. This is asserted by
`tests/test_data_processing.py::test_user_message_sends_only_the_fenced_document`.

## No-training / no-retention posture (enforced)

There is **no per-request "no-training" header** at either provider — it is the
default under their commercial API terms, and zero-retention (ZDR) is an
org-level agreement. The code therefore enforces the two things it can:

1. **Approved endpoint only.** Data goes only to a host on
   `LLM_ALLOWED_HOSTS` (default `api.anthropic.com`, `api.openai.com`). If a
   `*_BASE_URL` override points the SDK at a proxy/aggregator, the app
   **refuses to start** (fatal in every environment). See
   `app/llm/policy.py`.
2. **DPA acknowledged.** `LLM_NO_TRAINING_ACK=true` must be set once the
   provider's data-processing terms are filed (below). Required in production
   — the app refuses to boot without it; a warning in development.

Every extraction logs the provider/model that handled it (metadata only,
never content): the structured `extraction` event carries `llm_model` (e.g.
`anthropic:claude-haiku-4-5`), `engine`, `pages`, `duration_ms`.

## Provider terms (file the signed copies alongside this doc)

Both platforms state that **API inputs and outputs are not used to train
their models** by default. Retention differs and zero-retention requires an
explicit agreement.

- **Anthropic (Claude API)** — commercial terms exclude training on API
  data; Zero Data Retention available to eligible organisations.
  - Usage policy / commercial terms: https://www.anthropic.com/legal/commercial-terms
  - Privacy & data usage: https://privacy.anthropic.com/
  - **Action:** file the countersigned Anthropic DPA / ZDR confirmation as
    `docs/dpa/anthropic-dpa.pdf`.
- **OpenAI (API)** — API data not used for training since 2023-03-01; default
  ~30-day retention for abuse monitoring; Zero Data Retention available on
  approved endpoints/orgs.
  - API data usage policy: https://openai.com/policies/api-data-usage-policies
  - DPA: https://openai.com/policies/data-processing-addendum
  - **Action:** file the executed OpenAI DPA / ZDR confirmation as
    `docs/dpa/openai-dpa.pdf`. (The app currently runs on Anthropic; OpenAI
    only needs this if `LLM_PROVIDER` is switched.)

> Honest note on wording: setting `LLM_NO_TRAINING_ACK=true` asserts a
> **no-training** DPA is in place. **True zero-retention** requires the
> provider's ZDR agreement — arrange it if the brokerage's data policy demands
> no retention at all; otherwise the posture is *no training + limited
> provider-side retention for abuse monitoring* under the DPA.

## Verify

- Point `ANTHROPIC_BASE_URL` at a non-approved host → the app refuses to
  start (`… not on the approved no-training allowlist …`).
- Unset `LLM_NO_TRAINING_ACK` in production → the app refuses to start.
- Check logs: each extraction emits an `extraction` event with `llm_model`
  and no document content.
