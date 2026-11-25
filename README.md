# kitsune-vault 🦊

**One-way** sync of Firefox saved passwords into a **KeePassXC** database.

```
Firefox mobile ──(Firefox Sync, E2E)──> Firefox on the PC ──(kitsune-vault)──> vault.kdbx / "Firefox" group
```

Keep using Firefox on your mobile devices. Firefox Sync brings their passwords to
your PC, and kitsune-vault copies them into KeePassXC.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Linux only for now. The GUI needs Tkinter (`sudo apt install python3-tk` on Debian/Ubuntu).

## Graphical interface

```bash
.venv/bin/kitsune-vault-gui
```

1. Pick the Firefox profile and the `.kdbx` database (plus a key file if you use one).
2. Type the database password.
3. **Preview** lists what would be created, updated or trashed, without writing anything.
4. **Sync** asks for confirmation, makes a backup, then writes.

The GUI remembers the profile, database and key file paths in
`~/.config/kitsune-vault/gui.json`. It never stores a password.

## Command line

```bash
.venv/bin/kitsune-vault ~/Passwords.kdbx --dry-run   # show what would change
.venv/bin/kitsune-vault ~/Passwords.kdbx             # apply
```

| Option | Purpose |
|---|---|
| `--dry-run` | show creations, updates and trashed entries without writing |
| `--profile DIR` | Firefox profile (default: auto-detect: regular, snap, flatpak) |
| `--list-profiles` | list detected profiles |
| `--keyfile FILE` | KeePassXC key file |
| `--no-password` | database protected by a key file only |
| `--group NAME` | target group (default `Firefox`) |

Passwords are prompted at runtime. For unattended runs you can set
`KITSUNE_FIREFOX_PASSWORD` and `KITSUNE_KDBX_PASSWORD`, which are removed from the
environment as soon as they are read.

## Behaviour

- Each entry stores its Firefox ID in the `firefox-guid` attribute, so running the tool
  again never creates duplicates.
- **New** login: created. **Changed**: updated, with the previous version kept in the
  KeePass history. **Deleted** in Firefox: moved to the KeePass recycle bin, never
  permanently deleted.
- Only the `Firefox` group is touched.
- Before every write, a `vault.kdbx.kitsune-<date>.bak` backup is created. The 5 most
  recent are kept.

## Security

- The Firefox profile is never modified. The tool reads a copy in a `0700` temporary
  directory that is removed afterwards.
- Decryption uses the **NSS library bundled with Firefox**, the same version as `key4.db`.
- No secret is ever written in clear: no CSV, no log, no decrypted temporary file.
- No network access.
- Setting a Firefox primary password is **strongly recommended**.

## Limitations

- Passwords created in KeePassXC are **not** sent back to Firefox.
- **Lock or close KeePassXC** while syncing. KeePassXC reloads the modified file, but
  unsaved changes in its window could conflict.

## License

[MIT](LICENSE)
