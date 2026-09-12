# Key rotation & secret hygiene

All secrets are environment variables typed as `SecretStr` (never logged, never
in error responses, never committed — `.env` is git-ignored). Rotate on a
schedule and immediately on any suspected exposure.

## Password policy (ADMIN_PASSWORD and all users)

Enforced at seed time, at startup (fatal in production), and by the
`manage` CLI: **≥ 12 characters, not a known weak/default, a reasonable mix of
characters** (see `app/core/startup.py`).

## Rotating an LLM key (Anthropic / OpenAI)

1. Create a new key in the provider console.
2. Railway → Variables → update `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) →
   redeploy. New workers pick up the new key; no code change.
3. **Revoke the old key** in the provider console.
4. Zero downtime — extraction uses whichever key is live at request time.

> The OpenAI key shared in chat during development **must be revoked** at
> platform.openai.com and replaced. Since the app runs on Anthropic
> (`LLM_PROVIDER=anthropic`), you may simply remove `OPENAI_API_KEY` instead.

## Rotating an admin / user password

```bash
python -m app.manage set-password broker@ukcib.co.uk
```
Prompts for a new password (policy-enforced) and **signs that user out of all
sessions**. Use this to rotate the seeded admin credential.

## Rotating / invalidating sessions ("session secret")

There is no session signing secret to rotate — sessions are random tokens whose
**SHA-256 hashes** are stored server-side, so a DB leak exposes no usable
tokens. To force everyone to re-authenticate (suspected compromise, or after a
security change):

```bash
python -m app.manage logout-all
```

## Rotating the backup encryption key

`BACKUP_ENCRYPTION_KEY` decrypts existing backups, so do not discard the old
key while backups encrypted with it are still within the retention window:

1. Generate a new key: `python -m app.backup gen-key`.
2. Archive the **old** key somewhere safe (a password manager) until the last
   backup made with it has aged out of retention (≤ ~12 months).
3. Set the new key in Railway; the next backup uses it.
4. To restore an older backup during the overlap, temporarily set
   `BACKUP_ENCRYPTION_KEY` back to the archived old key.

## Where secrets live

- Railway → Variables (production). Never in the repo.
- Keep `BACKUP_ENCRYPTION_KEY` **also** in a password manager, separate from the
  backups themselves — without it, backups cannot be restored.
- `COOKIE_SECURE=true` and `APP_ENV=production` are required in production; the
  app refuses to boot otherwise (insecure cookie / weak admin password / no
  LLM key all fail startup).
