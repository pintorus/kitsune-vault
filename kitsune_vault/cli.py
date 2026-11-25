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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kitsune-vault", description=__doc__)
    ap.add_argument("database", type=Path, nargs="?", help="target .kdbx file")
    ap.add_argument("--profile", type=Path, help="Firefox profile (default: auto-detect)")
    ap.add_argument("--keyfile", type=Path, help="KeePassXC key file")
    ap.add_argument("--no-password", action="store_true", help="database protected by a key file only")
    ap.add_argument("--group", default="Firefox", help="target group (default: Firefox)")
    ap.add_argument("--dry-run", action="store_true", help="show changes without writing")
    ap.add_argument("--list-profiles", action="store_true")
    a = ap.parse_args(argv)

    profiles = find_profiles()
    if a.list_profiles:
        print("\n".join(map(str, profiles)) or "No profile found")
        return 0
    profile = a.profile or (profiles[0] if profiles else None)
    if not profile:
        print("No Firefox profile found, use --profile", file=sys.stderr)
        return 2
    if not a.database or not a.database.is_file():
        print(f"Database not found: {a.database}", file=sys.stderr)
        return 2

    try:
        with FirefoxVault(profile, lambda p: _secret("KITSUNE_FIREFOX_PASSWORD", p)) as fx:
            logins = fx.logins()
    except FirefoxError as e:
        print(f"Firefox: {e}", file=sys.stderr)
        return 1
    print(f"{len(logins)} logins read from {profile.name}")

    kp_pw = None if a.no_password else _secret("KITSUNE_KDBX_PASSWORD", "KeePassXC password: ")
    try:
        target = KeePassTarget(a.database, kp_pw, a.keyfile, a.group)
    except Exception as e:  # CredentialsError, corrupted file…
        print(f"KeePassXC: cannot open database ({type(e).__name__})", file=sys.stderr)
        return 1

    plan = target.plan(logins)
    for lg in plan.create:
        print(f"  + {_title(lg)}")
    for lg in plan.update:
        print(f"  ~ {_title(lg)}")
    for t in target.titles_for(plan.trash):
        print(f"  - {t} (recycle bin)")
    print(f"Created {len(plan.create)}, updated {len(plan.update)}, "
          f"trashed {len(plan.trash)}, unchanged {plan.unchanged}")

    if a.dry_run:
        print("--dry-run: nothing was written")
        return 0
    if not (plan.create or plan.update or plan.trash):
        return 0
    bak = backup(a.database)
    target.apply(plan)
    print(f"Database updated (backup: {bak.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
