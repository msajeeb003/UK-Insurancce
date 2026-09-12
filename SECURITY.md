# Security scanning & exception process

CI runs four automated scanners (`.github/workflows/security.yml`), plus
Dependabot for update PRs (`.github/dependabot.yml`). They run on every PR,
on push to `main`, and weekly.

| Scanner | Scope | Fails the build on |
|---|---|---|
| **pip-audit** | Python runtime deps (`backend/requirements.txt`) | any known advisory |
| **npm audit** | JS deps (only if `frontend/package.json` exists) | HIGH+ |
| **Trivy** | the built Docker image (OS + packages) | fixable HIGH / CRITICAL |
| **gitleaks** | working tree + full git history | any secret finding |
| **Dependabot** | pip, GitHub Actions, Docker base | opens update PRs |

## Fail policy

- **Dependencies (pip-audit):** fail on *any* advisory — triage, then either
  bump the dependency (preferred) or waive a specific one.
- **Image (Trivy):** fail on **fixable** HIGH/CRITICAL (`ignore-unfixed`), so
  un-fixable base-OS noise doesn't block work but actionable issues do.
- **Secrets (gitleaks):** fail on any finding. A genuine leak is an incident,
  not a waiver (see below).

## Exception process

Exceptions are **time-boxed, justified, and reviewer-approved** — never a
silent skip.

- **A dependency advisory** you cannot fix yet: add `--ignore-vuln <ID>` to the
  pip-audit step in `security.yml` with a trailing comment
  (`# why + review date`). Prefer bumping the dep.
- **An image CVE** with no fix or not reachable: add the CVE id to
  `.trivyignore` with a justification comment and review date.
- **A gitleaks false positive** (a placeholder/fixture): add a narrow path or
  regex to the `[allowlist]` in `.gitleaks.toml` with a comment. If the finding
  is a **real** secret: rotate it immediately (see docs/KEY_ROTATION.md), then
  scrub it from history (`git filter-repo`) — do not just allowlist it.

Every exception should name who approved it and when it will be revisited.
Open a short-lived issue to track removal.

## Reporting

Internal tool — report suspected vulnerabilities to the maintainer directly;
do not open a public issue with exploit detail.
