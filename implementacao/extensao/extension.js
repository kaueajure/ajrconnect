import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// Keep this loader stable. New behavior lives in modules with immutable URIs,
// so the Shell's ES-module cache can retain old modules without hiding updates.
const BRIDGE_INTERFACE = `<node>
<interface name="com.ajure.AJRConnect.Bridge">
  <method name="GetRevision"><arg type="s" direction="out" name="revision"/></method>
  <method name="Reload"><arg type="s" direction="out" name="revision"/></method>
</interface></node>`;

export default class AJRConnectBridge extends Extension {
    enable() {
        this._enabled = true;
        this._generation = (this._generation ?? 0) + 1;
        this._revision = '';
        this._runtime = null;
        this._stylesheet = null;
        this._themeContext = St.ThemeContext.get_for_stage(global.stage);
        this._theme = this._themeContext.get_theme();
        this._themeSignal = this._themeContext.connect('changed', () => {
            const theme = this._themeContext.get_theme();
            if (theme === this._theme) return;
            this._theme = theme;
            if (this._stylesheet) theme.load_stylesheet(this._stylesheet);
        });
        this._bridge = Gio.DBusExportedObject.wrapJSObject(BRIDGE_INTERFACE, this);
        this._bridge.export(Gio.DBus.session, '/com/ajure/AJRConnect/Bridge');
        this._reload().catch(error => console.error(`AJR Connect: ${error}`));
    }

    GetRevision() {
        return this._revision;
    }

    ReloadAsync(_args, invocation) {
        this._reload().then(revision => {
            invocation.return_value(new GLib.Variant('(s)', [revision]));
        }).catch(error => {
            invocation.return_dbus_error('com.ajure.AJRConnect.ReloadFailed', error.message);
        });
    }

    async _reload() {
        const generation = ++this._generation;
        const [ok, bytes] = this.dir.get_child('bridge.json').load_contents(null);
        if (!ok) throw new Error('Manifesto da integração indisponível.');
        const manifest = JSON.parse(new TextDecoder().decode(bytes));
        if (manifest.protocol !== 1 || !/^[a-f0-9]{64}$/.test(manifest.revision) ||
            !/^integration-[a-f0-9]{64}\.js$/.test(manifest.module) ||
            !/^style-[a-f0-9]{64}\.css$/.test(manifest.stylesheet))
            throw new Error('Manifesto da integração inválido.');
        if (this._runtime && manifest.revision === this._revision)
            return this._revision;

        // Import before touching the working runtime. Syntax/import errors leave
        // the current bar and shortcuts available.
        const module = await import(this.dir.get_child(manifest.module).get_uri());
        if (!this._enabled || generation !== this._generation)
            return this._revision;
        const candidate = new module.default();
        const stylesheet = this.dir.get_child(manifest.stylesheet);
        const theme = St.ThemeContext.get_for_stage(global.stage).get_theme();
        const previous = this._runtime;
        const previousStyle = this._stylesheet;
        const previousRevision = this._revision;
        previous?.disable();
        this._runtime = null;
        if (previousStyle) theme.unload_stylesheet(previousStyle);
        this._stylesheet = null;
        try {
            theme.load_stylesheet(stylesheet);
            candidate.enable();
            this._runtime = candidate;
            this._stylesheet = stylesheet;
            this._revision = manifest.revision;
        } catch (error) {
            try { candidate.disable(); } catch (cleanupError) { console.error(cleanupError); }
            theme.unload_stylesheet(stylesheet);
            this._revision = '';
            if (previous) {
                try {
                    if (previousStyle) theme.load_stylesheet(previousStyle);
                    previous.enable();
                    this._runtime = previous;
                    this._stylesheet = previousStyle;
                    this._revision = previousRevision;
                } catch (restoreError) {
                    console.error(`AJR Connect: ${restoreError}`);
                }
            }
            throw error;
        }
        return this._revision;
    }

    disable() {
        this._enabled = false;
        this._generation++;
        this._bridge?.unexport();
        this._bridge = null;
        if (this._themeSignal) this._themeContext.disconnect(this._themeSignal);
        this._themeSignal = 0;
        this._runtime?.disable();
        this._runtime = null;
        if (this._stylesheet)
            St.ThemeContext.get_for_stage(global.stage).get_theme().unload_stylesheet(this._stylesheet);
        this._stylesheet = null;
        this._themeContext = null;
        this._theme = null;
        this._revision = '';
    }
}
