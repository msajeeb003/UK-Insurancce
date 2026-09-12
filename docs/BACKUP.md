# Backup, durability & restore runbook

The container filesystem on Railway is **ephemeral** — it is wiped on every
redeploy. All durable state lives under `DATA_DIR` (SQLite DB, uploaded
documents, generated exports), which must be a **persistent volume**, and is
additionally backed up **encrypted and offsite** so it can be restored into a
clean instance.

---

## 1. Persistent volume (survives redeploys)

Railway → your service → **Variables**: confirm `DATA_DIR=/data`.
Railway → your service → **Volumes** → **New Volume**, mount path **`/data`**.

### Verify a redeploy no longer loses data
1. Sign in, create a project (note its client name).
2. Trigger a redeploy (push a commit, or Railway → Deploy).
3. After it restarts, sign in again — the project is still there.
4. Cross-check the logs: on a volume-backed instance the startup log shows
   **"Seeded initial user"** only on the *first ever* boot. If it appears on
   every redeploy, the volume is **not** attached (the DB is being recreated).

---

## 2. Backup configuration (`.env` / Railway variables)

```env
# Encryption (required). Generate once:  python -m app.backup gen-key
BACKUP_ENCRYPTION_KEY=<fernet-key>

# Offsite target — choose ONE. Use a DIFFERENT provider/region from the app
# (a separate bucket/region is the point of "offsite").
# (a) S3-compatible bucket (AWS EU / Cloudflare R2 / Backblaze B2 / Hetzner):
BACKUP_S3_BUCKET=ukcib-quote-backups
BACKUP_S3_ENDPOINT=https://<account>.r2.cloudflarestorage.com   # omit for AWS
BACKUP_S3_REGION=eu-central-1
BACKUP_S3_ACCESS_KEY=...
BACKUP_S3_SECRET_KEY=...
# (b) or a second mounted volume / directory:
# BACKUP_OFFSITE_DIR=/offsite

# Retention window (GFS): keep N daily + N monthly, prune the rest.
BACKUP_RETENTION_DAILY=30
BACKUP_RETENTION_MONTHLY=12

# Optional: POST {"text": "..."} to this URL on backup/integrity failure.
BACKUP_ALERT_WEBHOOK=
```

Each backup is a **consistent SQLite snapshot** (via the online backup API —
never a copy of the live file) **plus** the `projects/` document tree, tarred,
**Fernet-encrypted**, uploaded offsite, then old backups are pruned.

---

## 3. Schedule

Backups run from three places:

- **Every deploy (pre-migration):** the container entrypoint runs
  `python -m app.backup run --if-configured` **before** the server starts and
  before any schema migration executes on the first request — a safety net
  around risky releases. Best-effort: a transient offsite outage logs/alerts
  but does not block startup.
- **Every 6h + daily:** add a **Railway Cron** service (or any scheduler) that
  runs the image with command `python -m app.backup run`. Suggested crons:
  `0 */6 * * *` (6-hourly) and `30 2 * * *` (daily 02:30).
- **Integrity, daily:** a cron running `python -m app.backup integrity`
  (`PRAGMA integrity_check`); a non-zero exit + alert means the DB is
  corrupt — restore from the last good backup.

---

## 4. Restore (one command)

```bash
# list available backups (newest last)
python -m app.backup list

# restore a backup into a scratch directory to verify it first
python -m app.backup restore backup-YYYYMMDD-HHMMSS.tar.gz.enc --target /tmp/restore-check

# once verified, restore into the live DATA_DIR (stop the app first)
python -m app.backup restore backup-YYYYMMDD-HHMMSS.tar.gz.enc
```

Restore downloads → decrypts → unpacks `app.db` + `projects/`, and runs an
integrity check on the restored DB (it refuses a corrupt restore).

### Full disaster recovery (clean instance)
1. New Railway service from the same repo/image; attach a fresh `/data` volume.
2. Set the same `BACKUP_*` variables (same encryption key + offsite creds).
3. Run `python -m app.backup restore <name>` (via a one-off command / shell).
4. Start the service; sign in; confirm projects, documents and exports.

---

## 5. Restore drill result (executed 2026-09-12)

A full backup → simulated total data loss → restore was executed via the CLI
against a scratch dataset (SQLite DB + a 200 KB document):

| Metric | Value |
|---|---|
| Backup time | ~1.6 s (small dataset) |
| **RTO** (restore time, local) | ~1.5 s for download+decrypt+unpack; **~5–15 min end-to-end** on a clean Railway instance (dominated by provisioning + offsite download, not the restore) |
| **RPO** (max data loss) | **≤ 6 h** from the scheduled cadence; **≈ 0** for deploy-triggered loss (the pre-deploy hook backs up first) |
| Verification | DB row and the full document restored byte-for-byte; integrity check passed |

Automated coverage of the same path lives in `backend/tests/test_backup.py`
(encrypted round-trip, integrity, retention, no-op-when-unconfigured).

---

## 6. Operational notes

- **Keep the encryption key safe and separate** from the backups — without it,
  backups cannot be restored. Store it in a password manager, not only in
  Railway.
- Backups are held in memory during encryption; fine for the pilot's small
  dataset. Revisit if documents grow very large.
- The offsite bucket should be a **different account/region** from the app so a
  single-account compromise or region outage does not take both down.
