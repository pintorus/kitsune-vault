"""kitsune-vault: one-way sync of Firefox saved passwords into KeePassXC."""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from .firefox import FirefoxError, FirefoxVault, find_profiles
from .keepass import KeePassTarget, _title, backup


def _secret(env: str, prompt: str) -> str:
    v = os.environ.pop(env, None)  # removed from the environment once read
    return v if v is not None else getpass.getpass(prompt)


def _no_prompt(_prompt: str) -> str:
    raise FirefoxError("a Firefox primary password is set; unattended mode cannot unlock it")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kitsune-vault", description=__doc__)
    ap.add_argument("database", type=Path, nargs="?", help="target .kdbx file")
    ap.add_argument("--profile", type=Path, help="Firefox profile (default: auto-detect)")
    ap.add_argument("--keyfile", type=Path, help="KeePassXC key file")
    ap.add_argument("--no-password", action="store_true", help="database protected by a key file only")
    ap.add_argument("--group", default="Firefox", help="target group (default: Firefox)")
    ap.add_argument("--dry-run", action="store_true", help="show changes without writing")
    ap.add_argument("--list-profiles", action="store_true")
    un = ap.add_argument_group("unattended sync")
    un.add_argument("--store-password", action="store_true",
                    help="save the database password in the system keyring, then exit")
    un.add_argument("--forget-password", action="store_true",
                    help="remove the database password from the system keyring, then exit")
    un.add_argument("--use-keyring", action="store_true",
                    help="read the database password from the keyring, never prompt")
    un.add_argument("--install-timer", type=int, metavar="MINUTES",
                    help="sync every MINUTES via a systemd user timer (needs --store-password first)")
    un.add_argument("--uninstall-timer", action="store_true", help="remove the systemd timer")
    un.add_argument("--quiet", action="store_true", help="print the summary only (no entry names)")
    un.add_argument("--notify", action="store_true", help="desktop notification on changes or errors")
    a = ap.parse_args(argv)

    profiles = find_profiles()
    if a.list_profiles:
        print("\n".join(map(str, profiles)) or "No profile found")
        return 0
    if a.uninstall_timer:
        from .schedule import uninstall_timer
        uninstall_timer()
        print("Timer removed")
        return 0
    if not a.database or not a.database.is_file():
        print(f"Database not found: {a.database}", file=sys.stderr)
        return 2

    from . import schedule

    if a.store_password:
        schedule.store_password(a.database, getpass.getpass("KeePassXC password to store: "))
        print("Password stored in the system keyring")
        return 0
    if a.forget_password:
        schedule.forget_password(a.database)
        print("Password removed from the system keyring")
        return 0
    if a.install_timer:
        if not a.no_password and schedule.get_password(a.database) is None:
            print("No password in the keyring: run with --store-password first", file=sys.stderr)
            return 2
        schedule.install_timer(a.database, a.install_timer, a.keyfile, a.group, a.profile)
        print(f"Timer installed: sync every {a.install_timer} min "
              "(logs: journalctl --user -u kitsune-vault)")
        return 0

    def fail(msg: str) -> int:
        print(msg, file=sys.stderr)
        if a.notify:
            schedule.notify("kitsune-vault: sync failed", msg, error=True)
        return 1

    profile = a.profile or (profiles[0] if profiles else None)
    if not profile:
        return fail("No Firefox profile found, use --profile")

    ask = _no_prompt if a.use_keyring else (lambda p: _secret("KITSUNE_FIREFOX_PASSWORD", p))
    try:
        with FirefoxVault(profile, ask) as fx:
            logins = fx.logins()
    except FirefoxError as e:
        return fail(f"Firefox: {e}")
    if not a.quiet:
        print(f"{len(logins)} logins read from {profile.name}")

    if a.no_password:
        kp_pw = None
    elif a.use_keyring:
        try:
            kp_pw = schedule.get_password(a.database)
        except Exception as e:  # keyring locked or unavailable
            return fail(f"Keyring unavailable ({type(e).__name__})")
        if kp_pw is None:
            return fail("No password in the keyring: run with --store-password first")
    else:
        kp_pw = _secret("KITSUNE_KDBX_PASSWORD", "KeePassXC password: ")
    try:
        target = KeePassTarget(a.database, kp_pw, a.keyfile, a.group)
    except Exception as e:  # CredentialsError, corrupted file…
        return fail(f"KeePassXC: cannot open database ({type(e).__name__})")

    plan = target.plan(logins)
    if not a.quiet:
        for lg in plan.create:
            print(f"  + {_title(lg)}")
        for lg in plan.update:
            print(f"  ~ {_title(lg)}")
        for t in target.titles_for(plan.trash):
            print(f"  - {t} (recycle bin)")
    summary = (f"Created {len(plan.create)}, updated {len(plan.update)}, "
               f"trashed {len(plan.trash)}, unchanged {plan.unchanged}")
    print(summary)

    if a.dry_run:
        print("--dry-run: nothing was written")
        return 0
    if not (plan.create or plan.update or plan.trash):
        return 0
    bak = backup(a.database)
    try:
        target.apply(plan)
    except Exception as e:
        return fail(f"KeePassXC: write failed ({type(e).__name__}), backup kept: {bak.name}")
    print(f"Database updated (backup: {bak.name})")
    if a.notify:
        schedule.notify("kitsune-vault: passwords synced", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
