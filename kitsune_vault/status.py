"""Shared sync status, read by the GNOME top-bar indicator.

Written atomically to ~/.cache/kitsune-vault/status.json. Contains no secret:
only the state, a timestamp and the summary line (counts, no entry names).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

STATUS_FILE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "kitsune-vault" / "status.json"

RUNNING, OK, ERROR = "running", "ok", "error"


def write(state: str, message: str = "") -> None:
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {"state": state, "time": int(time.time()), "message": message, "pid": os.getpid()}
        fd, tmp = tempfile.mkstemp(dir=STATUS_FILE.parent, prefix=".status-")
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, STATUS_FILE)
    except OSError:
        pass  # the indicator is a convenience, never fail a sync because of it
