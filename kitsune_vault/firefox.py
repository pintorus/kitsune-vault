"""Read and decrypt the saved logins of a Firefox profile using NSS.

The profile is never modified: we work on a temporary copy (0700 directory,
removed afterwards) of key4.db / cert9.db / logins.json.
"""
from __future__ import annotations

import base64
import configparser
import ctypes
import ctypes.util
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

PROFILE_ROOTS = [
    Path.home() / ".mozilla/firefox",
    Path.home() / "snap/firefox/common/.mozilla/firefox",
    Path.home() / ".var/app/org.mozilla.firefox/.mozilla/firefox",
]

NSS_CANDIDATES = [
    "/snap/firefox/current/usr/lib/firefox/libnss3.so",
    "/usr/lib/firefox/libnss3.so",
    "/usr/lib64/firefox/libnss3.so",
]

PROFILE_FILES = ("key4.db", "cert9.db", "logins.json", "pkcs11.txt")


class FirefoxError(Exception):
    pass


@dataclass(frozen=True)
class Login:
    guid: str
    url: str
    username: str
    password: str
    time_password_changed: int  # ms epoch


# ---------------------------------------------------------------- profiles

def find_profiles() -> list[Path]:
    """Return the profiles, default profile first."""
    found: list[Path] = []
    for root in PROFILE_ROOTS:
        ini = root / "profiles.ini"
        if not ini.is_file():
            continue
        cfg = configparser.ConfigParser()
        cfg.read(ini)
        default_paths = {cfg[s]["Default"] for s in cfg.sections()
                         if s.startswith("Install") and "Default" in cfg[s]}
        entries = []
        for s in cfg.sections():
            if not s.startswith("Profile") or "Path" not in cfg[s]:
                continue
            rel = cfg[s].get("IsRelative", "1") == "1"
            p = (root / cfg[s]["Path"]) if rel else Path(cfg[s]["Path"])
            if (p / "logins.json").is_file():
                is_def = cfg[s]["Path"] in default_paths or cfg[s].get("Default") == "1"
                entries.append((not is_def, p))
        found += [p for _, p in sorted(entries)]
    return found


# ---------------------------------------------------------------- NSS

class _SECItem(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint),
                ("data", ctypes.POINTER(ctypes.c_ubyte)),
                ("len", ctypes.c_uint)]


_NSS_DEPS = ("libnspr4.so", "libplc4.so", "libplds4.so", "libnssutil3.so")


def _load_nss() -> ctypes.CDLL:
    """Prefer the NSS bundled with Firefox (same version as key4.db).

    Its dependencies are preloaded from the same directory, otherwise the
    dynamic linker picks the system ones, which are often older.
    """
    for c in NSS_CANDIDATES + [ctypes.util.find_library("nss3") or "libnss3.so"]:
        d = os.path.dirname(c)
        try:
            if d:
                for dep in _NSS_DEPS:
                    if os.path.exists(os.path.join(d, dep)):
                        ctypes.CDLL(os.path.join(d, dep), mode=ctypes.RTLD_GLOBAL)
            lib = ctypes.CDLL(c, mode=ctypes.RTLD_GLOBAL)
            break
        except OSError:
            continue
    else:
        raise FirefoxError("libnss3 not found (install libnss3)")
    lib.NSS_Init.argtypes = [ctypes.c_char_p]
    lib.NSS_Init.restype = ctypes.c_int
    lib.NSS_Shutdown.restype = ctypes.c_int
    lib.PK11_GetInternalKeySlot.restype = ctypes.c_void_p
    lib.PK11_FreeSlot.argtypes = [ctypes.c_void_p]
    lib.PK11_NeedLogin.argtypes = [ctypes.c_void_p]
    lib.PK11_NeedLogin.restype = ctypes.c_int
    lib.PK11_CheckUserPassword.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.PK11_CheckUserPassword.restype = ctypes.c_int
    lib.PK11SDR_Decrypt.argtypes = [ctypes.POINTER(_SECItem), ctypes.POINTER(_SECItem), ctypes.c_void_p]
    lib.PK11SDR_Decrypt.restype = ctypes.c_int
    lib.SECITEM_ZfreeItem.argtypes = [ctypes.POINTER(_SECItem), ctypes.c_int]
    return lib


class FirefoxVault:
    """Context manager: `with FirefoxVault(profile, ask_password) as v: v.logins()`."""

    def __init__(self, profile: Path, ask_password):
        self.profile = Path(profile)
        self._ask = ask_password
        self._tmp: str | None = None
        self._nss: ctypes.CDLL | None = None

    def __enter__(self):
        self._tmp = tempfile.mkdtemp(prefix="kitsune-")
        os.chmod(self._tmp, 0o700)
        for f in PROFILE_FILES:
            src = self.profile / f
            if src.is_file():
                shutil.copy2(src, self._tmp)
        if not os.path.isfile(os.path.join(self._tmp, "key4.db")):
            raise FirefoxError(f"key4.db not found in {self.profile}")
        self._nss = _load_nss()
        if self._nss.NSS_Init(f"sql:{self._tmp}".encode()) != 0:
            raise FirefoxError("NSS_Init failed")
        slot = self._nss.PK11_GetInternalKeySlot()
        try:
            if self._nss.PK11_NeedLogin(slot):
                pw = self._ask("Firefox primary password: ")
                if self._nss.PK11_CheckUserPassword(slot, pw.encode()) != 0:
                    raise FirefoxError("Wrong Firefox primary password")
        finally:
            self._nss.PK11_FreeSlot(slot)
        return self

    def __exit__(self, *exc):
        if self._nss is not None:
            self._nss.NSS_Shutdown()
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)

    def _decrypt(self, b64: str) -> str:
        raw = base64.b64decode(b64)
        buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        inp = _SECItem(0, buf, len(raw))
        out = _SECItem(0, None, 0)
        if self._nss.PK11SDR_Decrypt(ctypes.byref(inp), ctypes.byref(out), None) != 0:
            raise FirefoxError("Failed to decrypt an entry")
        try:
            return ctypes.string_at(out.data, out.len).decode("utf-8")
        finally:
            self._nss.SECITEM_ZfreeItem(ctypes.byref(out), 0)

    def logins(self) -> list[Login]:
        with open(os.path.join(self._tmp, "logins.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        out = []
        for e in data.get("logins", []):
            if e.get("deleted") or "encryptedPassword" not in e:
                continue  # Firefox Sync tombstone: deleted entry
            out.append(Login(
                guid=e["guid"],
                url=e.get("hostname") or "",
                username=self._decrypt(e["encryptedUsername"]),
                password=self._decrypt(e["encryptedPassword"]),
                time_password_changed=int(e.get("timePasswordChanged") or 0),
            ))
        return out
