"""Install and refresh the GNOME bridge without restarting the desktop."""
from pathlib import Path
import hashlib
import json
import shutil
import time
from core import atomic_json

EXTENSION_ID = 'ajr-connect@ajure.local'
BRIDGE_PATH = '/com/ajure/AJRConnect/Bridge'
BRIDGE_INTERFACE = 'com.ajure.AJRConnect.Bridge'
KEYBOARD_PATH = '/com/ajure/AJRConnect'
KEYBOARD_INTERFACE = 'com.ajure.AJRConnect.Keyboard'


def make_manifest(source):
    code = (source / 'integration.js').read_bytes()
    style = (source / 'stylesheet.css').read_bytes()
    code_hash = hashlib.sha256(code).hexdigest()
    style_hash = hashlib.sha256(style).hexdigest()
    return dict(protocol=1, revision=hashlib.sha256(code + b'\0' + style).hexdigest(),
                module=f'integration-{code_hash}.js', stylesheet=f'style-{style_hash}.css')


def install_extension(source, target):
    """Keep the loader stable and give each runtime module an immutable URI."""
    manifest = make_manifest(source)
    loader = source / 'extension.js'
    try:
        loader_changed = (target / 'extension.js').read_bytes() != loader.read_bytes()
    except OSError:
        loader_changed = True
    target.mkdir(parents=True, exist_ok=True)
    for original, name in [('integration.js', manifest['module']),
                           ('stylesheet.css', manifest['stylesheet'])]:
        destination = target / name
        if not destination.exists() or destination.read_bytes() != (source / original).read_bytes():
            shutil.copy2(source / original, destination)
    if loader_changed:
        shutil.copy2(loader, target / 'extension.js')
    shutil.copy2(source / 'metadata.json', target / 'metadata.json')
    # Publish the manifest only after both versioned files are complete.
    atomic_json(target / 'bridge.json', manifest)
    # Old installations let GNOME load this filename automatically. The bridge
    # now owns the versioned stylesheet and unloads it when replacing the runtime.
    (target / 'stylesheet.css').unlink(missing_ok=True)
    return manifest, loader_changed


def refresh_integration(revision, timeout=3):
    """Return a precise status; failures never restart GNOME or stop RDP."""
    from gi.repository import Gio, GLib
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync('org.gnome.Shell', '/org/gnome/Shell',
            'org.freedesktop.DBus.Peer', 'Ping', None, None,
            Gio.DBusCallFlags.NONE, 1000, None)
    except GLib.Error:
        return 'unavailable'

    def bridge_refresh():
        current = bus.call_sync('org.gnome.Shell', BRIDGE_PATH, BRIDGE_INTERFACE,
            'GetRevision', None, GLib.VariantType.new('(s)'),
            Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        if current != revision:
            current = bus.call_sync('org.gnome.Shell', BRIDGE_PATH, BRIDGE_INTERFACE,
                'Reload', None, GLib.VariantType.new('(s)'),
                Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        return current == revision

    try:
        if bridge_refresh():
            return 'ready'
    except GLib.Error:
        pass
    try:
        info = bus.call_sync('org.gnome.Shell', '/org/gnome/Shell',
            'org.gnome.Shell.Extensions', 'GetExtensionInfo',
            GLib.Variant('(s)', (EXTENSION_ID,)), None,
            Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        if not info:
            return 'not-discovered'
        if info.get('version', 0) < 8:
            return 'restart-required'
        bus.call_sync('org.gnome.Shell', '/org/gnome/Shell',
            'org.gnome.Shell.Extensions', 'EnableExtension',
            GLib.Variant('(s)', (EXTENSION_ID,)), None,
            Gio.DBusCallFlags.NONE, 1000, None)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if bridge_refresh():
                    return 'ready'
            except GLib.Error:
                pass
            time.sleep(.1)
    except GLib.Error:
        pass
    return 'failed'


def installed_revision():
    path = Path.home() / '.local/share/gnome-shell/extensions' / EXTENSION_ID / 'bridge.json'
    try:
        return json.loads(path.read_text())['revision']
    except (OSError, ValueError, KeyError, TypeError):
        return ''
