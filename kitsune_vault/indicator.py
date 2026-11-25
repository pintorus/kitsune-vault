"""Install the GNOME Shell top-bar indicator shipped in gnome_extension/."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

SRC = Path(__file__).resolve().parent / "gnome_extension"
UUID = json.loads((SRC / "metadata.json").read_text())["uuid"]
DEST = Path.home() / ".local/share/gnome-shell/extensions" / UUID


def install() -> str:
    DEST.mkdir(parents=True, exist_ok=True)
    for name in ("metadata.json", "extension.js", "stylesheet.css", "kitsune-symbolic.svg"):
        shutil.copy2(SRC / name, DEST / name)
    r = subprocess.run(["gnome-extensions", "enable", UUID], capture_output=True, text=True)
    if r.returncode == 0:
        return f"Indicator installed and enabled ({UUID})."
    # GNOME only discovers new extensions at login on Wayland.
    subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions",
                    _with_uuid()], check=False)
    return (f"Indicator installed in {DEST}.\n"
            "Log out and back in to load it (required on Wayland).")


def _with_uuid() -> str:
    r = subprocess.run(["gsettings", "get", "org.gnome.shell", "enabled-extensions"],
                       capture_output=True, text=True)
    cur = r.stdout.strip()
    try:
        items = json.loads(cur.replace("@as ", "").replace("'", '"'))
    except ValueError:
        items = []
    if UUID not in items:
        items.append(UUID)
    return "[" + ", ".join(f"'{i}'" for i in items) + "]"


def uninstall() -> None:
    subprocess.run(["gnome-extensions", "disable", UUID], capture_output=True)
    shutil.rmtree(DEST, ignore_errors=True)
