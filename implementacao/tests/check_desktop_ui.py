#!/usr/bin/env python3
"""Capture the real desktop UI in a private display/home, with example data only."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

BASE = Path(__file__).resolve().parents[1]
DRIVER = r'''
import contextlib, copy, sys, time, subprocess
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import ajr_app as gui
from ajr_app import Gtk, Gio, GLib, App, MainWindow
import gi
gi.require_version('GdkX11', '4.0')
from gi.repository import GdkX11
output = Path(sys.argv[2])
output.mkdir(parents=True, exist_ok=True)
def drain(duration=.3):
    end = time.monotonic() + duration
    while time.monotonic() < end:
        while GLib.MainContext.default().pending() and time.monotonic() < end:
            GLib.MainContext.default().iteration(False)
        time.sleep(.005)
def capture(window, name):
    drain()
    xid = GdkX11.X11Surface.get_xid(window.get_surface())
    subprocess.run(['import', '-window', str(xid), str(output / (name + '.png'))], check=True)
app = App()
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
monitors = [dict(id='0', connector='HDMI-1', width=1920, height=1080, x=0, y=0, primary=True)]
with patch.object(gui, 'secret', return_value=''), patch.object(gui, 'detect_monitors', return_value=monitors), \
        patch.object(gui.socket, 'create_connection', return_value=contextlib.nullcontext()):
    cfg = copy.deepcopy(gui.DEFAULT)
    for name, server, user in [('Escritório', 'escritorio.example', 'marina'),
                               ('Laboratório', 'lab.example:3390', 'equipe'),
                               ('Financeiro', 'financeiro.example', 'marina')]:
        cfg.update(active_profile='', server=server, user=user)
        gui.store_profile(cfg, name)
    gui.select_profile(cfg, cfg['profiles'][0]['id'])
    cfg['keyboard_shortcuts'] = [dict(accelerator='<Control><Alt>Left', remote=False),
                                dict(accelerator='<Control><Alt>Right', remote=False),
                                dict(accelerator='<Super>d', remote=True)]
    gui.save_cfg(cfg)
    win = MainWindow(app)
    win.set_default_size(1120, 880)
    win.present()
    drain(.6)
    win._integration_ready = True
    win.ui.integration_changed(True)
    win.update_keyboard_options()
    capture(win, 'ajr-connect-dark')
    win.ui.toggle_theme()
    capture(win, 'ajr-connect-light')
    win._available_release = gui.updates.Release('v6.0.0-beta.8', 100)
    with patch.object(gui.updates, 'installed_application', return_value=True):
        win.open_updates()
        capture(win._update_window, 'ajr-connect-updates')
    win._update_window.close()
    win.ui.show_page('display')
    capture(win, 'ajr-connect-keyboard')
    adjustment = win.ui.page_scrolls['display'].get_vadjustment()
    adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
    capture(win, 'ajr-connect-shortcuts')
    win.edit_keyboard_rule(0)
    editor = next(window for window in Gtk.Window.get_toplevels() if window.get_title() == 'Regra de teclado')
    capture(editor, 'ajr-connect-shortcut-editor')
    editor.close()
    win.ui.show_page('sharing')
    capture(win, 'ajr-connect-sharing')
    win.ui.toggle_theme()
    win.ui.show_page('connection')
    win.set_default_size(680, 760)
    drain(.4)
    assert win.ui.split.get_collapsed()
    capture(win, 'ajr-connect-compact')
    win.ui.sidebar_toggle.set_active(True)
    capture(win, 'ajr-connect-sidebar')
    win.ui.sidebar_toggle.set_active(False)
    win._retry_plan = gui.RetryPlan(delays=(30,) * 5)
    win.schedule_reconnect()
    capture(win, 'ajr-connect-reconnecting')
    win.cancel_connection()
    win.close()
    drain()
print('PASS: desktop, light/dark, shortcuts, updates, reconnecting and compact-sidebar captures')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sdk = BASE / 'tests/tools/sdk'
    xvfb = shutil.which('Xvfb') or str(sdk / 'usr/bin/Xvfb')
    if not Path(xvfb).is_file() or not shutil.which('import'):
        raise RuntimeError('Este teste precisa de Xvfb e ImageMagick (import).')
    with tempfile.TemporaryDirectory(prefix='ajr-ui-preview-') as directory:
        env = dict(os.environ, HOME=directory, XDG_CONFIG_HOME=directory + '/.config',
            XDG_DATA_HOME=directory + '/.local/share', XDG_CACHE_HOME=directory + '/.cache',
            GDK_BACKEND='x11', GSK_RENDERER='cairo', GSETTINGS_BACKEND='memory',
            DBUS_SESSION_BUS_ADDRESS='unix:path=/nonexistent',
            LD_LIBRARY_PATH=str(sdk / 'usr/lib/x86_64-linux-gnu'))
        server = subprocess.Popen([xvfb, '-displayfd', '1', '-screen', '0', '1600x1200x24',
            '-nolisten', 'tcp', '-noreset'], env=env, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True)
        try:
            env['DISPLAY'] = ':' + server.stdout.readline().strip()
            subprocess.run([sys.executable, '-c', DRIVER, str(BASE), str(args.output.resolve())],
                           env=env, check=True, timeout=35)
        finally:
            server.terminate()
            server.wait(timeout=5)
            server.stdout.close()


if __name__ == '__main__':
    main()
