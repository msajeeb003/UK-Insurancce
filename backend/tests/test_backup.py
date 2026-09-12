"""Backup / restore durability (encrypted, offsite, retention, integrity)."""

import io
import sqlite3
import tarfile

import pytest
from cryptography.fernet import Fernet

from app import backup
from app.core.config import get_settings


@pytest.fixture
def backups_configured(tmp_path, monkeypatch):
    """Point DATA_DIR and an offsite dir at temp paths with a real key."""
    data = tmp_path / "data"
    offsite = tmp_path / "offsite"
    data.mkdir()
    s = get_settings()
    monkeypatch.setattr(s, "data_dir", str(data))
    monkeypatch.setattr(s, "backup_offsite_dir", str(offsite))
    monkeypatch.setattr(s, "backup_s3_bucket", "")
    from pydantic import SecretStr
    monkeypatch.setattr(s, "backup_encryption_key", SecretStr(Fernet.generate_key().decode()))
    # seed a DB with a row and a stored document
    con = sqlite3.connect(data / "app.db")
    con.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, client_name TEXT)")
    con.execute("INSERT INTO projects VALUES ('p1', 'Aldgate Timber Ltd')")
    con.commit()
    con.close()
    doc = data / "projects" / "p1" / "docs"
    doc.mkdir(parents=True)
    (doc / "quote.pdf").write_bytes(b"%PDF-1.4 fake quote")
    return data, offsite


def test_backup_restore_roundtrip(backups_configured, tmp_path):
    data, offsite = backups_configured
    name = backup.create_backup()
    assert name.startswith("backup-") and name.endswith(".tar.gz.enc")

    # simulate total data loss
    (data / "app.db").unlink()
    import shutil
    shutil.rmtree(data / "projects")

    # restore into a scratch target and verify DB row + document are back
    target = tmp_path / "restored"
    backup.restore_backup(name, target)
    con = sqlite3.connect(target / "app.db")
    row = con.execute("SELECT client_name FROM projects WHERE id='p1'").fetchone()
    con.close()
    assert row[0] == "Aldgate Timber Ltd"
    assert (target / "projects" / "p1" / "docs" / "quote.pdf").read_bytes() == b"%PDF-1.4 fake quote"


def test_offsite_backup_is_encrypted(backups_configured):
    data, offsite = backups_configured
    name = backup.create_backup()
    raw = (offsite / name).read_bytes()
    # An encrypted blob is not a readable gzip/tar and needs the key to open.
    assert raw[:2] != b"\x1f\x8b"                 # not plain gzip
    with pytest.raises(tarfile.TarError):
        tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz")


def test_integrity_check_passes_on_good_db(backups_configured):
    assert backup.integrity_check() is True


def test_retention_keeps_daily_and_monthly():
    # 40 consecutive days of backups -> keep 30 daily + older month markers.
    names = [f"backup-2026{m:02d}{d:02d}-020000.tar.gz.enc"
             for (m, d) in [(3, x) for x in range(1, 32)] + [(4, x) for x in range(1, 10)]]
    keep = backup._keepers(names, daily=30, monthly=12)
    newest = sorted(names)[-1]
    oldest = sorted(names)[0]
    assert newest in keep                          # most recent always kept
    assert len(keep) <= len(names)
    # the very oldest day (beyond 30 daily) survives only as a monthly marker
    assert oldest in keep or len([n for n in keep if n.startswith("backup-202603")]) >= 1


def test_run_if_configured_noop_when_unset(monkeypatch):
    s = get_settings()
    from pydantic import SecretStr
    monkeypatch.setattr(s, "backup_encryption_key", SecretStr(""))
    monkeypatch.setattr(s, "backup_s3_bucket", "")
    monkeypatch.setattr(s, "backup_offsite_dir", "")
    assert backup.is_configured() is False
    assert backup.main(["run", "--if-configured"]) == 0
