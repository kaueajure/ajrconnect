#!/usr/bin/env python3
"""Update the actual extension inside a private GNOME 46 session; no RDP/keyring."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

BASE = Path(__file__).resolve().parents[1]

DRIVER = r'''
import json, subprocess, sys, time
from pathlib import Path
from gi.repository import Gio, GLib
sys.path.insert(0, sys.argv[1])
from integration import install_extension, refresh_integration, EXTENSION_ID, BRIDGE_PATH, BRIDGE_INTERFACE
source = Path.home() / 'source'
target = Path.home() / '.local/share/gnome-shell/extensions' / EXTENSION_ID
initial, _ = install_extension(source, target)
original_code = (source / 'integration.js').read_text()
settings = Gio.Settings.new('org.gnome.shell')
settings.set_strv('enabled-extensions', [EXTENSION_ID])
Gio.Settings.sync()
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
def revision():
    return bus.call_sync('org.gnome.Shell', BRIDGE_PATH, BRIDGE_INTERFACE,
        'GetRevision', None, GLib.VariantType.new('(s)'),
        Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
def ping():
    return bus.call_sync('org.gnome.Shell', '/com/ajure/AJRConnect',
        'com.ajure.AJRConnect.Keyboard', 'Ping', None,
        GLib.VariantType.new('(b)'), Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
with (Path.home() / 'gnome.log').open('w') as log:
    shell = subprocess.Popen(['gnome-shell', '--headless', '--wayland',
        '--virtual-monitor', '1024x768', '--sm-disable'], stdout=log, stderr=subprocess.STDOUT)
    pid = shell.pid
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if revision() == initial['revision']: break
            except GLib.Error:
                pass
            if shell.poll() is not None: raise RuntimeError('GNOME isolado encerrou')
            time.sleep(.1)
        else: raise RuntimeError('Timeout carregando ponte')
        assert ping() is True
        changed = original_code.replace('return !Main.sessionMode.isLocked;', 'return false;', 1)
        assert changed != original_code
        (source / 'integration.js').write_text(changed)
        updated, loader_changed = install_extension(source, target)
        assert not loader_changed
        assert refresh_integration(updated['revision']) == 'ready'
        assert revision() == updated['revision'] and ping() is False
        assert shell.poll() is None and shell.pid == pid
        # Restore the previous cached module while the same Shell keeps running.
        (source / 'integration.js').write_text(original_code)
        restored, _ = install_extension(source, target)
        assert refresh_integration(restored['revision']) == 'ready'
        assert ping() is True and shell.poll() is None
        # Failed import keeps the working bar; failed enable restores it.
        for broken in [original_code + "\nthrow new Error('test import failure');\n",
                       original_code.replace('this._sync();\n    }\n\n    Ping()',
                       "this._sync();\n        throw new Error('test enable failure');\n    }\n\n    Ping()", 1)]:
            assert broken != original_code
            (source / 'integration.js').write_text(broken)
            rejected, _ = install_extension(source, target)
            assert refresh_integration(rejected['revision'], timeout=.15) == 'failed'
            assert revision() == restored['revision'] and ping() is True
            assert shell.poll() is None and shell.pid == pid
        (source / 'integration.js').write_text(original_code)
        restored, _ = install_extension(source, target)
        assert refresh_integration(restored['revision']) == 'ready'
        print('PASS GNOME 46: live update, cached-module rollback, failed import/enable recovery; Shell PID unchanged', flush=True)
    finally:
        shell.terminate()
        try: shell.wait(timeout=5)
        except subprocess.TimeoutExpired: shell.kill(); shell.wait()
'''


def main():
    if not shutil.which('gnome-shell') or not shutil.which('dbus-run-session'):
        raise RuntimeError('Este teste precisa de GNOME Shell 46 e dbus-run-session.')
    with tempfile.TemporaryDirectory(prefix='ajr-live-update-') as directory:
        root = Path(directory)
        runtime = root / 'runtime'
        runtime.mkdir(mode=0o700)
        shutil.copytree(BASE / 'extensao', root / 'source')
        env = dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / '.config'),
            XDG_DATA_HOME=str(root / '.local/share'), XDG_CACHE_HOME=str(root / '.cache'),
            XDG_RUNTIME_DIR=str(runtime), LIBGL_ALWAYS_SOFTWARE='1', GSETTINGS_BACKEND='dconf',
            GNOME_SHELL_SESSION_MODE='user')
        for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS'):
            env.pop(key, None)
        result = subprocess.run(['dbus-run-session', '--', sys.executable, '-c', DRIVER, str(BASE)],
            env=env, capture_output=True, text=True, timeout=45)
        if result.returncode:
            print(result.stderr)
            if (root / 'gnome.log').exists(): print((root / 'gnome.log').read_text())
            return result.returncode
        print(result.stdout.strip())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
