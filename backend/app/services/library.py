"""Mapping library + insurer rules, loaded from config/ as data (BRD 2.3/2.4).

insurers.json (standing list, aliases, debt rule) and terminology.json
(field -> insurer wordings) are configuration, not code — re-read on mtime
change, so edits take effect without a release.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any

from app.core.errors import ConfigurationError

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"

_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}  # path -> (mtime, parsed)


def _load_json(filename: str) -> Any:
    """Read a config file, caching by modification time (thread-safe)."""
    path = CONFIG_DIR / filename
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError as exc:
        raise ConfigurationError(
            f"config/{filename} is missing — restore it from the repository."
        ) from exc
    with _lock:
        cached = _cache.get(filename)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            # A stale cached copy is safer than crashing mid-edit; fall back
            # if we have one, otherwise surface a clear operator error.
            if cached:
                logger.error(
                    "config/%s is invalid JSON (%s) — keeping previous version",
                    filename, exc,
                )
                return cached[1]
            raise ConfigurationError(
                f"config/{filename} is not valid JSON — fix the file syntax."
            ) from exc
        _cache[filename] = (mtime, data)
        logger.info("Loaded config/%s (mtime %s)", filename, mtime)
        return data


def get_insurers() -> list[dict]:
    """The standing insurer list: [{id, name, debt_collection}, ...]."""
    return _load_json("insurers.json")["insurers"]


def get_terminology() -> dict[str, list[str]]:
    """field name -> list of insurer wordings that map onto that row."""
    return _load_json("terminology.json")["fields"]


def _alias_map() -> dict[str, str]:
    """lowercased alias/name -> insurer id."""
    data = _load_json("insurers.json")
    out: dict[str, str] = {}
    for ins in data["insurers"]:
        out[ins["name"].lower()] = ins["id"]
    for ins_id, names in data.get("aliases", {}).items():
        if ins_id == "_comment":
            continue
        for name in names:
            out[name.lower()] = ins_id
    return out


def match_insurer(extracted_name: str | None) -> dict | None:
    """
    Match an extracted insurer name against the standing list, using the
    configured aliases (case-insensitive substring both ways).
    """
    if not extracted_name:
        return None
    needle = extracted_name.lower().strip()
    aliases = _alias_map()
    hit_id = aliases.get(needle)
    if hit_id is None:
        for alias, ins_id in aliases.items():
            if alias in needle or needle in alias:
                hit_id = ins_id
                break
    if hit_id is None:
        return None
    return next((i for i in get_insurers() if i["id"] == hit_id), None)


def debt_collection_rule(extracted_name: str | None) -> tuple[str, str | None]:
    """
    BRD 2.4: Allianz, Atradius and Coface default to Included; every other
    insurer (and an unrecognised one) defaults to Outsourced. Returns
    (value, matched standing-list name or None). Editable per column in the
    UI — this only sets the default.
    """
    matched = match_insurer(extracted_name)
    if matched is None:
        return "Outsourced", None
    value = "Included" if matched["debt_collection"] == "included" else "Outsourced"
    return value, matched["name"]
