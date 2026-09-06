"""
Mapping library + insurer rules, loaded from `config/` as DATA (BRD 2.3/2.4).

Two files drive extraction quality and the debt-collection rule:

    config/insurers.json     standing insurer list, aliases, and the
                             debt-collection rule (included / outsourced)
    config/terminology.json  what each insurer calls each comparison row

Both are configuration, not code — the BRD requires that adding an insurer,
moving one between Included and Outsourced, or extending the terminology
mapping never needs a release. Files are re-read automatically when their
modification time changes, so an edit takes effect on the next request
without restarting the server.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"

_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}  # path -> (mtime, parsed)


def _load_json(filename: str) -> Any:
    """Read a config file, caching by modification time (thread-safe)."""
    path = CONFIG_DIR / filename
    mtime = path.stat().st_mtime
    with _lock:
        cached = _cache.get(filename)
        if cached and cached[0] == mtime:
            return cached[1]
        data = json.loads(path.read_text(encoding="utf-8"))
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
