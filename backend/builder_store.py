"""
builder_store.py — disk persistence for saved builder strategies ("My Strategies").

The earlier `saved_strategies` dict lived only in memory and vanished on every
server restart. This is a tiny JSON-file store so a strategy a user builds
survives restarts. It holds opaque builder payloads (legs, conditions, targets,
settings) — the backend never interprets them, it just round-trips them to the
Builder UI.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

STORE_PATH = Path(os.environ.get(
    "BUILDER_STORE_PATH",
    Path(__file__).parent.parent / "saved_builder_strategies.json",
)).resolve()

_lock = threading.Lock()


def _read() -> Dict[str, dict]:
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write(data: Dict[str, dict]) -> None:
    # Atomic write so a crash mid-save can't corrupt the store.
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(STORE_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, STORE_PATH)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def list_strategies() -> List[dict]:
    """Saved strategies, newest first (without their full payload)."""
    items = _read().values()
    out = [{"id": v["id"], "name": v["name"], "updated_at": v["updated_at"]} for v in items]
    return sorted(out, key=lambda x: x["updated_at"], reverse=True)


def get_strategy(sid: str) -> Optional[dict]:
    return _read().get(sid)


def save_strategy(name: str, payload: Any, sid: Optional[str] = None) -> dict:
    """Create or overwrite a saved strategy. Returns the stored record."""
    with _lock:
        data = _read()
        if not sid or sid not in data:
            sid = sid or uuid.uuid4().hex[:8]
            created = datetime.now(timezone.utc).isoformat()
        else:
            created = data[sid].get("created_at")
        record = {
            "id": sid,
            "name": name or "Untitled",
            "payload": payload,
            "created_at": created,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        data[sid] = record
        _write(data)
        return record


def delete_strategy(sid: str) -> bool:
    with _lock:
        data = _read()
        if sid in data:
            del data[sid]
            _write(data)
            return True
        return False
