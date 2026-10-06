import St from 'gi://St';
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as AltTab from 'resource:///org/gnome/shell/ui/altTab.js';

const KEYBOARD_INTERFACE = `<node>
<interface name="com.ajure.AJRConnect.Keyboard">
  <method name="Ping"><arg type="b" direction="out" name="ready"/></method>
  <method name="GetKeyboardVersion"><arg type="u" direction="out" name="version"/></method>
  <method name="LocalAccelerator">
    <arg type="u" direction="in" name="pid"/>
    <arg type="s" direction="in" name="token"/>
    <arg type="u" direction="in" name="keyval"/>
    <arg type="u" direction="in" name="modifiers"/>
    <arg type="u" direction="in" name="keycode"/>
    <arg type="b" direction="out" name="accepted"/>
  </method>
  <method name="LocalShortcut">
    <arg type="u" direction="in" name="pid"/>
    <arg type="s" direction="in" name="token"/>
    <arg type="u" direction="in" name="action"/>
    <arg type="b" direction="in" name="reverse"/>
    <arg type="b" direction="out" name="accepted"/>
  </method>
</interface></node>`;

// The Shell presents controls; the RDP client owns every fullscreen transition.
export default class AJRConnectIntegration {
    enable() {
        this._sources = new Set();
        this._signals = [];
        this._windows = new Map();
        this._target = null;
        this._hideSource = 0;
        this._bar = new St.BoxLayout({style_class: 'ajr-bar', reactive: true,
            track_hover: true, visible: false});
        this._brand = new St.Label({text: 'AJR Connect', style_class: 'ajr-brand',
            y_align: Clutter.ActorAlign.CENTER});
        this._bar.add_child(this._brand);
        this._button('window-minimize-symbolic', 'Minimizar', 'minimize');
        this._button('view-restore-symbolic', 'Sair de tela cheia', 'restore');
        this._button('window-close-symbolic', 'Desconectar', 'disconnect', true);
        this._hotZone = new St.Widget({reactive: true, track_hover: true,
            style_class: 'ajr-hot-zone', visible: false});
        // trackFullscreen=false deliberately keeps the AJR controls above fullscreen.
        for (const actor of [this._bar, this._hotZone]) {
            Main.layoutManager.addTopChrome(actor, {
                affectsStruts: false, trackFullscreen: false, affectsInputRegion: true,
            });
            this._connect(actor, 'enter-event', () => {
                this._show();
                return Clutter.EVENT_PROPAGATE;
            });
            this._connect(actor, 'leave-event', () => {
                this._scheduleHide();
                return Clutter.EVENT_PROPAGATE;
            });
        }
        this._connect(global.display, 'window-created', (_display, win) => this._watch(win));
        this._connect(global.display, 'notify::focus-window', () => this._sync());
        this._connect(Main.layoutManager, 'monitors-changed', () => this._sync());
        this._connect(Main.overview, 'showing', () => this._sync());
        this._connect(Main.overview, 'hidden', () => this._sync());
        this._connect(Main.sessionMode, 'updated', () => this._sync());
        for (const actor of global.get_window_actors()) this._watch(actor.meta_window);
        this._keyboardDBus = Gio.DBusExportedObject.wrapJSObject(KEYBOARD_INTERFACE, this);
        this._keyboardDBus.export(Gio.DBus.session, '/com/ajure/AJRConnect');
        this._sync();
    }

    Ping() {
        return !Main.sessionMode.isLocked;
    }

    GetKeyboardVersion() {
        return 2;
    }

    LocalAccelerator(pid, token, keyval, modifiers, keycode) {
        const win = global.display.focus_window;
        const record = win ? this._record(win) : null;
        if (Main.sessionMode.isLocked || !record || record.pid !== pid || record.token !== token ||
            !keyval || keycode < 8 || keycode > 255 || modifiers & ~77)
            return false;
        // Use the desktop's existing bindings, including user-created ones.
        // Reject unbound shortcuts before generating any input.
        if (!global.display.get_keybinding_action(keycode, modifiers))
            return false;
        this._virtualKeyboard ??= Clutter.get_default_backend().get_default_seat()
            .create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
        const keys = [[4, Clutter.KEY_Control_L], [8, Clutter.KEY_Alt_L],
            [1, Clutter.KEY_Shift_L], [64, Clutter.KEY_Super_L]]
            .filter(([mask]) => modifiers & mask).map(([, key]) => key);
        keys.push(keyval);
        const time = GLib.get_monotonic_time();
        const pressed = [];
        try {
            for (const key of keys) {
                this._virtualKeyboard.notify_keyval(time, key, Clutter.KeyState.PRESSED);
                pressed.push(key);
            }
        } finally {
            for (const key of pressed.reverse())
                this._virtualKeyboard.notify_keyval(time, key, Clutter.KeyState.RELEASED);
        }
        return true;
    }

    LocalShortcut(pid, token, action, reverse) {
        // Validate the same private runtime token used by the session controls.
        // Never act on arbitrary applications or while the desktop is locked.
        const win = global.display.focus_window;
        const record = win ? this._record(win) : null;
        if (Main.sessionMode.isLocked || !record || record.pid !== pid || record.token !== token)
            return false;
        if (action === 1) {
            this._switcher?.destroy();
            const settings = new Gio.Settings({schema_id: 'org.gnome.desktop.wm.keybindings'});
            const windows = settings.get_strv('switch-windows').some(key =>
                /^(<Alt>|<Mod1>)Tab$/.test(key));
            const popup = windows ? new AltTab.WindowSwitcherPopup() : new AltTab.AppSwitcherPopup();
            this._switcher = popup;
            popup.connect('destroy', () => { if (this._switcher === popup) this._switcher = null; });
            if (!popup.show(reverse, windows ? 'switch-windows' : 'switch-applications', Clutter.ModifierType.MOD1_MASK))
                popup.destroy();
        } else if (action === 2) {
            Main.overview.toggle();
        } else if (action === 3) {
            win.delete(global.get_current_time());
        } else {
            return false;
        }
        return true;
    }

    _connect(object, signal, callback, owner = null) {
        const id = object.connect(signal, callback);
        this._signals.push({object, id, owner});
    }

    _later(milliseconds, callback) {
        const id = GLib.timeout_add(GLib.PRIORITY_DEFAULT, milliseconds, () => {
            this._sources.delete(id);
            callback();
            return GLib.SOURCE_REMOVE;
        });
        this._sources.add(id);
        return id;
    }

    _cancel(id) {
        if (id && this._sources.delete(id)) GLib.source_remove(id);
    }

    _record(win) {
        if (win.get_wm_class() !== 'AJRConnect' || win.get_title() !== 'AJR Connect VM')
            return null;
        const pid = win.get_pid();
        const path = GLib.build_filenamev([GLib.get_user_runtime_dir(),
            'ajr-connect', `session-${pid}.json`]);
        try {
            const [ok, bytes] = GLib.file_get_contents(path);
            if (!ok) return null;
            const record = JSON.parse(new TextDecoder().decode(bytes));
            return record.pid === pid && /^[a-f0-9]{8}$/.test(record.token) ? record : null;
        } catch (_) {
            return null;
        }
    }

    _watch(win) {
        if (!win || this._windows.has(win)) return;
        this._windows.set(win, null);
        const update = () => {
            this._windows.set(win, this._record(win));
            this._sync();
        };
        for (const signal of ['notify::title', 'notify::wm-class', 'notify::fullscreen',
            'notify::minimized', 'position-changed', 'size-changed'])
            this._connect(win, signal, update, win);
        this._connect(win, 'unmanaged', () => {
            this._windows.delete(win);
            this._disconnectOwner(win);
            this._sync();
        }, win);
        update();
        // Only startup gets a bounded retry; stable sessions are driven by signals.
        this._later(500, () => { if (this._windows.has(win)) update(); });
        this._later(1800, () => { if (this._windows.has(win)) update(); });
    }

    _disconnectOwner(owner) {
        this._signals = this._signals.filter(entry => {
            if (entry.owner !== owner) return true;
            entry.object.disconnect(entry.id);
            return false;
        });
    }

    _button(icon, label, command, danger = false) {
        const button = new St.Button({style_class: `ajr-button${danger ? ' ajr-danger' : ''}`,
            reactive: true, can_focus: true, track_hover: true, accessible_name: label});
        button.set_child(new St.Icon({icon_name: icon, icon_size: 18}));
        // Visible labels avoid relying on the meaning of icons alone.
        const contents = new St.BoxLayout({style_class: 'ajr-button-content'});
        contents.add_child(new St.Icon({icon_name: icon, icon_size: 16}));
        contents.add_child(new St.Label({text: label, y_align: Clutter.ActorAlign.CENTER}));
        button.set_child(contents);
        this._connect(button, 'clicked', () => this._command(command));
        this._bar.add_child(button);
    }

    _usable() {
        const win = global.display.focus_window;
        return win && this._windows.get(win) && win.is_fullscreen() && !win.minimized &&
            win.showing_on_its_workspace() && !Main.overview.visible &&
            !Main.sessionMode.isLocked ? win : null;
    }

    _sync() {
        const win = this._usable();
        if (win !== this._target) this._hide();
        this._target = win;
        if (!win) {
            this._hotZone.hide();
            this._hide();
            return;
        }
        const monitor = Main.layoutManager.monitors[win.get_monitor()];
        if (!monitor) {
            this._hotZone.hide();
            this._hide();
            return;
        }
        const width = Math.min(560, monitor.width - 32);
        this._hotZone.set_position(Math.round(monitor.x + (monitor.width - width) / 2), monitor.y);
        this._hotZone.set_size(width, 8);
        this._hotZone.show();
        this._bar.set_position(Math.round(monitor.x + (monitor.width - width) / 2), monitor.y + 4);
        this._bar.set_width(width);
        this._brand.set_text('AJR Connect');
    }

    _show() {
        if (!this._usable()) return;
        this._cancel(this._hideSource);
        this._hideSource = 0;
        this._bar.show();
    }

    _hide() {
        this._cancel(this._hideSource);
        this._hideSource = 0;
        this._bar?.hide();
    }

    _scheduleHide() {
        this._cancel(this._hideSource);
        this._hideSource = this._later(600, () => {
            this._hideSource = 0;
            if (!this._bar.hover && !this._hotZone.hover) this._hide();
        });
    }

    _command(command) {
        const win = this._target;
        const record = win ? this._windows.get(win) : null;
        if (!record) return;
        const helper = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'share',
            'ajr-connect', 'app', 'ajr-control']);
        try {
            const process = Gio.Subprocess.new([helper, String(record.pid), command],
                Gio.SubprocessFlags.STDERR_PIPE);
            process.communicate_utf8_async(null, null, (_proc, result) => {
                try {
                    const [, , error] = process.communicate_utf8_finish(result);
                    if (!process.get_successful())
                        Main.notify('AJR Connect', error.trim() || 'Não foi possível controlar a sessão.');
                } catch (error) {
                    console.error(`AJR Connect: ${error}`);
                }
            });
        } catch (error) {
            Main.notify('AJR Connect', `Não foi possível executar o controle: ${error.message}`);
        }
        this._hide();
    }

    disable() {
        this._keyboardDBus?.unexport();
        this._keyboardDBus = null;
        this._switcher?.destroy();
        this._switcher = null;
        this._virtualKeyboard = null;
        for (const id of this._sources ?? []) GLib.source_remove(id);
        this._sources?.clear();
        for (const {object, id} of this._signals ?? []) object.disconnect(id);
        this._signals = [];
        this._windows?.clear();
        this._target = null;
        for (const actor of [this._bar, this._hotZone]) {
            if (!actor) continue;
            Main.layoutManager.removeChrome(actor);
            actor.destroy();
        }
        this._bar = this._hotZone = null;
    }
}
