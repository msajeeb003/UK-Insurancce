# Deployment guide

> **Why not Vercel?** Vercel runs stateless serverless functions: no
> persistent disk (the SQLite DB, retained documents and exports would
> vanish between requests), a ~250 MB function limit (the OCR stack
> alone is bigger) and request timeouts shorter than an LLM extraction.
> Use a platform that runs a persistent container instead — Railway /
> Render below need no server administration at all, or use any VPS
> with section B.

## A. Quick deploy without a VPS — Railway (or Render)

The repo now carries a `Dockerfile`, so any container platform deploys
it straight from GitHub.

**Railway** (recommended — persistent volume, EU region, ~$5/month):

1. railway.app → New Project → **Deploy from GitHub repo** →
   `msajeeb003/UK-Insurancce` (it auto-detects the Dockerfile).
2. Settings → Region: **europe-west4 (Amsterdam)** — EU hosting, BRD 2.11.
3. Right-click the service → **Attach Volume** → mount path `/data`
   (the SQLite DB, retained documents and exports live there).
4. Variables tab:

   ```env
   ANTHROPIC_API_KEY=sk-ant-...
   LLM_PROVIDER=anthropic
   ADMIN_EMAIL=broker@ukcib.co.uk
   ADMIN_PASSWORD=<strong password>
   COOKIE_SECURE=true
   DATA_DIR=/data
   ```

5. Settings → Networking → **Generate Domain** → HTTPS is automatic.
   Open the URL, sign in with the admin credentials.

**Render** works the same way (New Web Service → this repo → Docker,
region Frankfurt, add a Disk mounted at `/data`, same variables) — but
note its free tier has **no persistent disk** and sleeps between
requests, so a paid instance is required for real use.

Scanned-PDF OCR note: the default image skips the heavy open-source OCR
stack. Scanned PDFs need either Azure Document Intelligence keys in the
variables, or a rebuild with `--build-arg INSTALL_OCR=1` (several-GB
image).

## B. Hetzner VPS (EU hosting, BRD 2.11)

One small VPS runs everything: FastAPI + the SQLite database + stored
documents. No separate database server is needed at this scale
(3–4 internal users, BRD 2.10) — backing up the app means copying the
`data/` directory.

### 1. Server

- Hetzner Cloud VPS (e.g. CX22), **Falkenstein or Nuremberg (Germany)**
  — satisfies the BRD 2.11 UK/EU hosting requirement.
- Ubuntu 24.04. Enable Hetzner's backups for the volume.

```bash
apt update && apt install -y python3.11-venv git caddy
git clone https://github.com/msajeeb003/UK-Insurancce.git /opt/quote-tool
cd /opt/quote-tool
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-ocr.txt
```

### 2. Configuration — `/opt/quote-tool/.env`

```env
ANTHROPIC_API_KEY=sk-ant-...
LLM_PROVIDER=anthropic

# First user (seeded once, when the users table is empty)
ADMIN_EMAIL=broker@ukcib.co.uk
ADMIN_PASSWORD=<strong password>

# Behind HTTPS:
COOKIE_SECURE=true

# Storage (SQLite DB + retained documents + exports)
DATA_DIR=/opt/quote-tool/data
```

Add further users (no self-registration, BRD 2.10):

```bash
cd /opt/quote-tool && .venv/bin/python -m app.manage add-user second.broker@ukcib.co.uk
```

### 3. Service — `/etc/systemd/system/quote-tool.service`

```ini
[Unit]
Description=Insurance Quote Comparison Tool
After=network.target

[Service]
WorkingDirectory=/opt/quote-tool
ExecStart=/opt/quote-tool/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
chown -R www-data:www-data /opt/quote-tool
systemctl enable --now quote-tool
```

### 4. HTTPS — `/etc/caddy/Caddyfile`

Caddy terminates TLS with an automatic Let's Encrypt certificate
(encryption in transit, BRD 2.11):

```
quotes.example.co.uk {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
systemctl reload caddy
```

The app binds to 127.0.0.1 only — nothing is reachable except through
Caddy. No client or insurer access; no sharing links (BRD rules).

### 5. Data handling (BRD 2.11)

- **Encryption in transit**: TLS via Caddy (above).
- **Encryption at rest**: use an encrypted Hetzner volume for
  `DATA_DIR`, or enable full-disk encryption on the VPS image.
- **Access**: only the named users can sign in; sessions expire after
  `SESSION_TTL_HOURS` (default 72).
- **Model training**: documents are sent to the Claude API for
  extraction only; API data is not used to train models.
- **Retention / deletion on request**: deleting a project removes its
  database rows, retained documents and generated exports:

  ```bash
  curl -X DELETE https://quotes.example.co.uk/projects/<project-id> -b "qct_session=<session>"
  ```

  The retention period itself is a client decision (BRD open item) —
  agree it before go-live.
- **Backups**: stop-free — copy `/opt/quote-tool/data` (SQLite WAL is
  snapshot-safe with `sqlite3 data/app.db ".backup backup.db"`).

### 6. Update a release

```bash
cd /opt/quote-tool && git pull && systemctl restart quote-tool
```
