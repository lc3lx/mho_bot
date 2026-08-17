"""Temporary debug NDJSON logger for session 73d636. Remove after verification."""
from __future__ import annotations

import json
import time
from pathlib import Path

_LOG = Path(__file__).resolve().parent / "debug-73d636.log"


def dbg(hypothesis_id: str, location: str, message: str, data: dict | None = None, run_id: str = "pre"):
    # #region agent log
    try:
        payload = {
            "sessionId": "73d636",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with _LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion
