# kitsune-vault 🦊

Synchro **à sens unique** des mots de passe Firefox vers une base **KeePassXC**.

```
Firefox mobile ──(Firefox Sync, E2E)──> Firefox du PC ──(kitsune-vault)──> base.kdbx / groupe "Firefox"
```

Les mobiles continuent d'utiliser Firefox. Firefox Sync remonte leurs mots de passe
sur le PC, et kitsune-vault les recopie dans KeePassXC.

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Utilisation

```bash
.venv/bin/kitsune-vault ~/Passwords.kdbx --dry-run   # voir ce qui changerait
.venv/bin/kitsune-vault ~/Passwords.kdbx             # appliquer
```

| Option | Rôle |
|---|---|
| `--dry-run` | affiche les créations, mises à jour et mises à la corbeille, sans écrire |
| `--profile DIR` | profil Firefox (sinon détection auto : classique, snap, flatpak) |
| `--list-profiles` | liste les profils détectés |
| `--keyfile FILE` | fichier clé KeePassXC |
| `--no-password` | base protégée par fichier clé seul |
| `--group NAME` | groupe cible (défaut `Firefox`) |

Les mots de passe sont demandés à l'exécution. Pour une exécution automatisée, on peut
utiliser `KITSUNE_FIREFOX_PASSWORD` et `KITSUNE_KDBX_PASSWORD`, qui sont retirées de
l'environnement dès leur lecture.

## Comportement

- Chaque entrée garde l'identifiant Firefox dans l'attribut `firefox-guid`, donc
  relancer l'outil ne crée pas de doublons.
- **Nouvelle** entrée : elle est créée. **Modifiée** : elle est mise à jour et l'ancienne
  version reste dans l'historique KeePass. **Supprimée** dans Firefox : elle part à la
  corbeille KeePass, jamais de suppression définitive.
- Seul le groupe `Firefox` est touché.
- Avant chaque écriture, une sauvegarde `base.kdbx.kitsune-<date>.bak` est créée.
  Les 5 dernières sont conservées.

## Sécurité

- Le profil Firefox n'est jamais modifié. L'outil lit une copie dans un dossier
  temporaire en `0700`, supprimé à la fin.
- Le déchiffrement passe par la **NSS livrée avec Firefox**, même version que `key4.db`.
- Aucun secret n'est écrit en clair : pas de CSV, pas de log, pas de fichier temporaire
  déchiffré.
- Aucun accès réseau.
- Il est **fortement recommandé** d'activer un mot de passe principal Firefox.

## Limites

- Les mots de passe créés dans KeePassXC **ne remontent pas** vers Firefox.
- **Verrouillez ou fermez KeePassXC** pendant la synchro. KeePassXC recharge le fichier
  modifié, mais des changements non enregistrés dans l'interface pourraient entrer en
  conflit.
