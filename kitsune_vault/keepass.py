"""Synchronisation à sens unique Firefox -> KeePassXC (.kdbx) via pykeepass."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from pykeepass import PyKeePass

from .firefox import Login

GUID_KEY = "firefox-guid"
CHANGED_KEY = "firefox-time-password-changed"


@dataclass
class Plan:
    create: list[Login] = field(default_factory=list)
    update: list[Login] = field(default_factory=list)
    trash: list[str] = field(default_factory=list)   # titres d'entrées
    unchanged: int = 0


def _title(login: Login) -> str:
    host = urlparse(login.url).hostname or login.url
    return f"{host} ({login.username})" if login.username else host


def backup(db_path: Path, keep: int = 5) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = db_path.with_name(f"{db_path.name}.kitsune-{stamp}.bak")
    shutil.copy2(db_path, dst)
    dst.chmod(0o600)
    olds = sorted(db_path.parent.glob(f"{db_path.name}.kitsune-*.bak"))
    for old in olds[:-keep]:
        old.unlink()
    return dst


class KeePassTarget:
    def __init__(self, path: Path, password: str | None, keyfile: Path | None, group: str):
        self.kp = PyKeePass(str(path), password=password,
                            keyfile=str(keyfile) if keyfile else None)
        self.group = (self.kp.find_groups(name=group, group=self.kp.root_group, first=True)
                      or self.kp.add_group(self.kp.root_group, group))

    def _index(self):
        idx = {}
        for e in self.group.entries:
            g = e.get_custom_property(GUID_KEY)
            if g:
                idx[g] = e
        return idx

    def plan(self, logins: list[Login]) -> Plan:
        idx = self._index()
        p = Plan()
        seen = set()
        for lg in logins:
            seen.add(lg.guid)
            e = idx.get(lg.guid)
            if e is None:
                p.create.append(lg)
            elif (e.password != lg.password or e.username != lg.username or e.url != lg.url):
                p.update.append(lg)
            else:
                p.unchanged += 1
        p.trash = [g for g in idx if g not in seen]
        return p

    def apply(self, plan: Plan) -> None:
        idx = self._index()
        for lg in plan.create:
            e = self.kp.add_entry(self.group, _title(lg), lg.username, lg.password,
                                  url=lg.url, force_creation=True)
            e.set_custom_property(GUID_KEY, lg.guid)
            e.set_custom_property(CHANGED_KEY, str(lg.time_password_changed))
        for lg in plan.update:
            e = idx[lg.guid]
            e.save_history()
            e.username, e.password, e.url = lg.username, lg.password, lg.url
            e.set_custom_property(CHANGED_KEY, str(lg.time_password_changed))
            e.touch(modify=True)
        for g in plan.trash:
            self.kp.trash_entry(idx[g])
        self.kp.save()

    def titles_for(self, guids: list[str]) -> list[str]:
        idx = self._index()
        return [idx[g].title for g in guids]
