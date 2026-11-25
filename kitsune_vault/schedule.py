"""Unattended sync: password in the system keyring + systemd user timer.

The KeePassXC password is stored in the desktop keyring (Secret Service,
e.g. GNOME Keyring), which is encrypted on disk and unlocked at login.
The timer therefore only syncs while your session is open.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SERVICE = "kitsune-vault"
UNIT = "kitsune-vault"
UNIT_DIR = Path.home() / ".config/systemd/user"


# ---------------------------------------------------------------- keyring

def _keyring():
    import keyring  # imported lazily: only needed for unattended mode
    return keyring


def store_password(db: Path, password: str) -> None:
    _keyring().set_password(SERVICE, str(Path(db).resolve()), password)


def get_password(db: Path) -> str | None:
    return _keyring().get_password(SERVICE, str(Path(db).resolve()))


def forget_password(db: Path) -> None:
    kr = _keyring()
    try:
        kr.delete_password(SERVICE, str(Path(db).resolve()))
    except kr.errors.PasswordDeleteError:
        pass


# ---------------------------------------------------------------- notifications

def notify(summary: str, body: str = "", error: bool = False) -> None:
    if shutil.which("notify-send"):
        icon = Path(__file__).resolve().parent / "assets" / "kitsune-vault.png"
        subprocess.run(["notify-send", "-a", "kitsune-vault", "-i", str(icon),
                        "-u", "critical" if error else "low", summary, body],
                       check=False)


# ---------------------------------------------------------------- systemd timer

def _cli_exe() -> Path:
    exe = Path(sys.executable).parent / "kitsune-vault"
    if not exe.exists():
        raise RuntimeError(f"kitsune-vault command not found next to {sys.executable}")
    return exe


def _systemctl(*args) -> None:
    subprocess.run(["systemctl", "--user", *args], check=True)


def install_timer(db: Path, interval_min: int = 15, keyfile: Path | None = None,
                  group: str = "Firefox", profile: Path | None = None) -> None:
    args = [str(_cli_exe()), str(Path(db).resolve()), "--use-keyring", "--quiet", "--notify"]
    if keyfile:
        args += ["--keyfile", str(Path(keyfile).resolve())]
    if profile:
        args += ["--profile", str(Path(profile).resolve())]
    if group != "Firefox":
        args += ["--group", group]
    cmd = " ".join(f'"{a}"' if " " in a else a for a in args)
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    (UNIT_DIR / f"{UNIT}.service").write_text(
        "[Unit]\nDescription=kitsune-vault: sync Firefox passwords into KeePassXC\n\n"
        f"[Service]\nType=oneshot\nExecStart={cmd}\nNice=10\n")
    (UNIT_DIR / f"{UNIT}.timer").write_text(
        "[Unit]\nDescription=Run kitsune-vault periodically\n\n"
        f"[Timer]\nOnActiveSec=1min\nOnStartupSec=2min\nOnUnitActiveSec={int(interval_min)}min\nPersistent=true\n\n"
        "[Install]\nWantedBy=timers.target\n")
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", f"{UNIT}.timer")


def uninstall_timer() -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", f"{UNIT}.timer"],
                   check=False, capture_output=True)
    for ext in ("timer", "service"):
        (UNIT_DIR / f"{UNIT}.{ext}").unlink(missing_ok=True)
    _systemctl("daemon-reload")


def timer_active() -> bool:
    r = subprocess.run(["systemctl", "--user", "is-active", f"{UNIT}.timer"],
                       capture_output=True, text=True, check=False)
    return r.stdout.strip() == "active"
