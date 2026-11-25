"""Tkinter GUI for kitsune-vault.

No secret is ever stored: only the database, key file and profile paths are
remembered in ~/.config/kitsune-vault/gui.json.
"""
from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .firefox import FirefoxError, FirefoxVault, find_profiles
from .keepass import KeePassTarget, _title, backup

CONFIG = Path.home() / ".config/kitsune-vault/gui.json"


def _load_cfg() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def _save_cfg(cfg: dict) -> None:
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(cfg, indent=2))
    except OSError:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("kitsune-vault — Firefox → KeePassXC")
        self.minsize(640, 480)
        self._events: queue.Queue = queue.Queue()
        self._busy = False
        cfg = _load_cfg()

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        # Firefox profile
        ttk.Label(frm, text="Firefox profile").grid(row=0, column=0, sticky="w", pady=3)
        self.profiles = [str(p) for p in find_profiles()]
        self.profile = tk.StringVar(value=cfg.get("profile") if cfg.get("profile") in self.profiles
                                    else (self.profiles[0] if self.profiles else ""))
        ttk.Combobox(frm, textvariable=self.profile, values=self.profiles,
                     state="readonly").grid(row=0, column=1, columnspan=2, sticky="ew")

        # KeePassXC database
        ttk.Label(frm, text="KeePassXC database").grid(row=1, column=0, sticky="w", pady=3)
        self.db = tk.StringVar(value=cfg.get("database", ""))
        ttk.Entry(frm, textvariable=self.db).grid(row=1, column=1, sticky="ew")
        ttk.Button(frm, text="Browse…", command=self._pick_db).grid(row=1, column=2, padx=(6, 0))

        # Key file (optional)
        ttk.Label(frm, text="Key file (optional)").grid(row=2, column=0, sticky="w", pady=3)
        self.keyfile = tk.StringVar(value=cfg.get("keyfile", ""))
        ttk.Entry(frm, textvariable=self.keyfile).grid(row=2, column=1, sticky="ew")
        ttk.Button(frm, text="Browse…", command=self._pick_key).grid(row=2, column=2, padx=(6, 0))

        # Password
        ttk.Label(frm, text="Password").grid(row=3, column=0, sticky="w", pady=3)
        self.pw = tk.StringVar()
        pw_entry = ttk.Entry(frm, textvariable=self.pw, show="•")
        pw_entry.grid(row=3, column=1, columnspan=2, sticky="ew")
        pw_entry.bind("<Return>", lambda _e: self._run(dry=True))

        # Group
        ttk.Label(frm, text="Target group").grid(row=4, column=0, sticky="w", pady=3)
        self.group = tk.StringVar(value=cfg.get("group", "Firefox"))
        ttk.Entry(frm, textvariable=self.group, width=20).grid(row=4, column=1, sticky="w")

        # Buttons
        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(10, 6))
        self.btn_preview = ttk.Button(btns, text="Preview", command=lambda: self._run(dry=True))
        self.btn_sync = ttk.Button(btns, text="Sync", command=lambda: self._run(dry=False))
        self.btn_preview.pack(side="left")
        self.btn_sync.pack(side="left", padx=6)
        self.progress = ttk.Progressbar(btns, mode="indeterminate", length=120)
        self.progress.pack(side="right")

        # Results
        cols = ("action", "entry")
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", height=12)
        self.tree.heading("action", text="Action")
        self.tree.heading("entry", text="Entry")
        self.tree.column("action", width=110, stretch=False)
        self.tree.grid(row=6, column=0, columnspan=3, sticky="nsew")
        sb = ttk.Scrollbar(frm, orient="vertical", command=self.tree.yview)
        sb.grid(row=6, column=3, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        frm.rowconfigure(6, weight=1)

        self.status = tk.StringVar(value="Lock KeePassXC before syncing.")
        ttk.Label(frm, textvariable=self.status).grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))

        if not self.profiles:
            self.status.set("No Firefox profile found.")
        self.after(100, self._poll)

    # ------------------------------------------------------------ file pickers
    def _pick_db(self):
        p = filedialog.askopenfilename(title="KeePassXC database",
                                       filetypes=[("KeePass", "*.kdbx"), ("All files", "*")])
        if p:
            self.db.set(p)

    def _pick_key(self):
        p = filedialog.askopenfilename(title="Key file")
        if p:
            self.keyfile.set(p)

    # ------------------------------------------------------------ run
    def _run(self, dry: bool):
        if self._busy:
            return
        db = Path(self.db.get()).expanduser()
        if not self.profile.get():
            return messagebox.showerror("kitsune-vault", "No Firefox profile selected.")
        if not db.is_file():
            return messagebox.showerror("kitsune-vault", f"Database not found:\n{db}")
        if not dry and not messagebox.askyesno(
                "Sync",
                "Write to the database?\nA .bak backup will be created first.\n\n"
                "KeePassXC must be locked or closed."):
            return
        _save_cfg({"profile": self.profile.get(), "database": str(db),
                   "keyfile": self.keyfile.get(), "group": self.group.get()})
        self._set_busy(True)
        self.tree.delete(*self.tree.get_children())
        args = (Path(self.profile.get()), db, self.pw.get() or None,
                Path(self.keyfile.get()).expanduser() if self.keyfile.get() else None,
                self.group.get() or "Firefox", dry)
        threading.Thread(target=self._worker, args=args, daemon=True).start()

    def _ask_firefox_pw(self, prompt: str) -> str:
        """Called from the worker thread: delegates the dialog to the Tk thread."""
        box: dict = {}
        done = threading.Event()
        self._events.put(("ask", prompt, box, done))
        done.wait()
        if box.get("pw") is None:
            raise FirefoxError("Cancelled")
        return box["pw"]

    def _worker(self, profile, db, pw, keyfile, group, dry):
        post = self._events.put
        try:
            post(("status", "Reading Firefox…"))
            with FirefoxVault(profile, self._ask_firefox_pw) as fx:
                logins = fx.logins()
            post(("status", f"{len(logins)} logins read. Opening database…"))
            try:
                target = KeePassTarget(db, pw, keyfile, group)
            except Exception as e:
                raise RuntimeError(f"Cannot open database ({type(e).__name__}).\n"
                                   "Check the password and key file.") from None
            plan = target.plan(logins)
            rows = ([("+ create", _title(l)) for l in plan.create]
                    + [("~ update", _title(l)) for l in plan.update]
                    + [("− trash", t) for t in target.titles_for(plan.trash)])
            post(("rows", rows))
            summary = (f"Created {len(plan.create)}, updated {len(plan.update)}, "
                       f"trashed {len(plan.trash)}, unchanged {plan.unchanged}")
            if dry:
                post(("done", summary + " — preview, nothing written."))
            elif not rows:
                post(("done", summary + " — already up to date."))
            else:
                bak = backup(db)
                target.apply(plan)
                post(("done", summary + f" — database updated (backup {bak.name})."))
        except FirefoxError as e:
            post(("error", f"Firefox: {e}"))
        except Exception as e:
            post(("error", str(e) or type(e).__name__))

    def _poll(self):
        try:
            while True:
                ev = self._events.get_nowait()
                kind = ev[0]
                if kind == "status":
                    self.status.set(ev[1])
                elif kind == "rows":
                    for r in ev[1]:
                        self.tree.insert("", "end", values=r)
                elif kind == "done":
                    self.status.set(ev[1])
                    self._set_busy(False)
                elif kind == "error":
                    self.status.set("Failed.")
                    self._set_busy(False)
                    messagebox.showerror("kitsune-vault", ev[1])
                elif kind == "ask":
                    _, prompt, box, done = ev
                    box["pw"] = simpledialog.askstring("Firefox", prompt, show="•", parent=self)
                    done.set()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _set_busy(self, busy: bool):
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.btn_preview.configure(state=state)
        self.btn_sync.configure(state=state)
        if busy:
            self.progress.start(10)
        else:
            self.progress.stop()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
