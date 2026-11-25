"""kitsune-vault : synchro à sens unique Firefox -> KeePassXC."""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from .firefox import FirefoxError, FirefoxVault, find_profiles
from .keepass import KeePassTarget, _title, backup


def _secret(env: str, prompt: str) -> str:
    v = os.environ.pop(env, None)  # retiré de l'environnement dès lecture
    return v if v is not None else getpass.getpass(prompt)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kitsune-vault", description=__doc__)
    ap.add_argument("database", type=Path, nargs="?", help="fichier .kdbx cible")
    ap.add_argument("--profile", type=Path, help="profil Firefox (défaut : auto)")
    ap.add_argument("--keyfile", type=Path, help="fichier clé KeePassXC")
    ap.add_argument("--no-password", action="store_true", help="base protégée par fichier clé seul")
    ap.add_argument("--group", default="Firefox", help="groupe cible (défaut : Firefox)")
    ap.add_argument("--dry-run", action="store_true", help="affiche les changements sans écrire")
    ap.add_argument("--list-profiles", action="store_true")
    a = ap.parse_args(argv)

    profiles = find_profiles()
    if a.list_profiles:
        print("\n".join(map(str, profiles)) or "Aucun profil trouvé")
        return 0
    profile = a.profile or (profiles[0] if profiles else None)
    if not profile:
        print("Aucun profil Firefox trouvé, utilisez --profile", file=sys.stderr)
        return 2
    if not a.database or not a.database.is_file():
        print(f"Base introuvable : {a.database}", file=sys.stderr)
        return 2

    try:
        with FirefoxVault(profile, lambda p: _secret("KITSUNE_FIREFOX_PASSWORD", p)) as fx:
            logins = fx.logins()
    except FirefoxError as e:
        print(f"Firefox : {e}", file=sys.stderr)
        return 1
    print(f"{len(logins)} identifiants lus depuis {profile.name}")

    kp_pw = None if a.no_password else _secret("KITSUNE_KDBX_PASSWORD", "Mot de passe KeePassXC : ")
    try:
        target = KeePassTarget(a.database, kp_pw, a.keyfile, a.group)
    except Exception as e:  # CredentialsError, fichier corrompu…
        print(f"KeePassXC : ouverture impossible ({type(e).__name__})", file=sys.stderr)
        return 1

    plan = target.plan(logins)
    for lg in plan.create:
        print(f"  + {_title(lg)}")
    for lg in plan.update:
        print(f"  ~ {_title(lg)}")
    for t in target.titles_for(plan.trash):
        print(f"  - {t} (corbeille)")
    print(f"Créations {len(plan.create)}, mises à jour {len(plan.update)}, "
          f"corbeille {len(plan.trash)}, inchangées {plan.unchanged}")

    if a.dry_run:
        print("--dry-run : rien n'a été écrit")
        return 0
    if not (plan.create or plan.update or plan.trash):
        return 0
    bak = backup(a.database)
    target.apply(plan)
    print(f"Base mise à jour (sauvegarde : {bak.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
