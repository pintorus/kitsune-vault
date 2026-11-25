// kitsune-vault top-bar indicator for GNOME Shell 45+.
// Reads ~/.cache/kitsune-vault/status.json (written by kitsune-vault) and shows
// the sync state: running / ok / error. Contains no secret.

import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import St from 'gi://St';
import GObject from 'gi://GObject';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const STALE_RUNNING_SEC = 600; // a "running" state older than this is treated as an error

// Same fox icon for every state; the colour tells the state (see stylesheet.css).
const STATES = {
    running: {style: 'kitsune-running', label: 'Sync in progress…'},
    ok:      {style: 'kitsune-ok',      label: 'Last sync OK'},
    error:   {style: 'kitsune-error',   label: 'Last sync failed'},
    unknown: {style: 'kitsune-unknown', label: 'No sync yet'},
};

function statusPath() {
    return GLib.build_filenamev([GLib.get_user_cache_dir(), 'kitsune-vault', 'status.json']);
}

function readStatus() {
    try {
        const [ok, bytes] = GLib.file_get_contents(statusPath());
        if (!ok)
            return null;
        return JSON.parse(new TextDecoder().decode(bytes));
    } catch (_e) {
        return null;
    }
}

function formatTime(epoch) {
    const dt = GLib.DateTime.new_from_unix_local(epoch);
    return dt ? dt.format('%H:%M') : '';
}

const KitsuneIndicator = GObject.registerClass(
class KitsuneIndicator extends PanelMenu.Button {
    _init(extPath) {
        super._init(0.5, 'kitsune-vault');
        this._icon = new St.Icon({
            style_class: 'system-status-icon',
            gicon: Gio.icon_new_for_string(`${extPath}/kitsune-symbolic.svg`),
        });
        this.add_child(this._icon);

        this._stateItem = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._detailItem = new PopupMenu.PopupMenuItem('', {reactive: false});
        this.menu.addMenuItem(this._stateItem);
        this.menu.addMenuItem(this._detailItem);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this.menu.addAction('Sync now', () => this._spawn(
            ['systemctl', '--user', 'start', '--no-block', 'kitsune-vault.service']));
        this.menu.addAction('Open kitsune-vault', () => this._spawn(['gtk-launch', 'kitsune-vault']));

        const dir = Gio.File.new_for_path(GLib.path_get_dirname(statusPath()));
        try {
            dir.make_directory_with_parents(null);
        } catch (_e) { /* already exists */ }
        this._monitor = dir.monitor_directory(Gio.FileMonitorFlags.NONE, null);
        this._monitorId = this._monitor.connect('changed', () => this._refresh());
        // Re-check every minute so a stale "running" state and "x min ago" stay accurate.
        this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 60, () => {
            this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
        this._refresh();
    }

    _spawn(argv) {
        try {
            Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
        } catch (e) {
            Main.notifyError('kitsune-vault', e.message);
        }
    }

    _refresh() {
        const st = readStatus();
        let key = st && STATES[st.state] ? st.state : 'unknown';
        let detail = st ? (st.message || '') : 'Waiting for the first sync';
        if (key === 'running' && GLib.get_real_time() / 1e6 - st.time > STALE_RUNNING_SEC) {
            key = 'error';
            detail = 'Sync stopped unexpectedly';
        }
        const s = STATES[key];
        for (const k of Object.keys(STATES))
            this._icon.remove_style_class_name(STATES[k].style);
        this._icon.add_style_class_name(s.style);
        this._stateItem.label.text = st ? `${s.label} · ${formatTime(st.time)}` : s.label;
        this._detailItem.label.text = detail;
        this._detailItem.visible = detail !== '';
    }

    destroy() {
        if (this._timerId) {
            GLib.source_remove(this._timerId);
            this._timerId = 0;
        }
        if (this._monitor) {
            this._monitor.disconnect(this._monitorId);
            this._monitor.cancel();
            this._monitor = null;
        }
        super.destroy();
    }
});

export default class KitsuneVaultExtension extends Extension {
    enable() {
        this._indicator = new KitsuneIndicator(this.path);
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
