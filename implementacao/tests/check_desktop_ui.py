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
    if isinstance(window, MainWindow):
        validate_layout(window)
    xid = GdkX11.X11Surface.get_xid(window.get_surface())
    subprocess.run(['import', '-window', str(xid), str(output / (name + '.png'))], check=True)
def validate_layout(window):
    # Vertical scrolling is intentional; hidden horizontal overflow is not.
    scroll = window.ui.page_scrolls[window.form.get_visible_child_name()]
    adjustment = scroll.get_hadjustment()
    assert adjustment.get_upper() <= adjustment.get_page_size() + 1, 'Horizontal page overflow'
    widgets = [*window.ui.tab_buttons.values(), window.connect_btn, window.ui.save_button,
               window.status, window.profile_name, window.server, window.user, window.password,
               window.controls, window.error, window.monitor, window.fullscreen, window.shortcut,
               window.quality, window.keyboard_mode, window.keyboard_rules, window.share_list,
               window.clipboard, window.ui.empty_share_state]
    for widget in widgets:
        if not widget.get_mapped():
            continue
        ok, bounds = widget.compute_bounds(window)
        assert ok
        assert bounds.get_x() >= 0 and bounds.get_x() + bounds.get_width() <= window.get_width(), \
            ('Control clipped horizontally', widget, bounds.get_x(), bounds.get_width(), window.get_width())
    for widget in [*window.ui.tab_buttons.values(), window.connect_btn]:
        ok, bounds = widget.compute_bounds(window)
        assert ok and bounds.get_y() >= 0 and bounds.get_y() + bounds.get_height() <= window.get_height(), \
            'Navigation or primary action clipped vertically'
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
    # UI cases below exercise an available keyboard backend. Consent/rejection
    # get separate captures, without contacting the user's real portal.
    win.set_default_size(1120, 820)
    win.present()
    drain(.6)
    win._integration_ready = True
    win.integration_banner.set_revealed(False)
    win.ui.integration_changed(True)
    win.update_keyboard_options()
    capture(win, 'ajr-connect-dark')
    win.ui.toggle_theme()
    capture(win, 'ajr-connect-light')
    win._available_release = gui.updates.Release('v6.0.0-beta.10', 100)
    with patch.object(gui.updates, 'installed_application', return_value=True):
        win.open_updates()
        capture(win._update_window, 'ajr-connect-updates')
        win.ui.toggle_theme()
        capture(win._update_window, 'ajr-connect-updates-dark')
        win.ui.toggle_theme()
    win._update_window.close()
    win.ui.show_page('display')
    capture(win, 'ajr-connect-keyboard')
    adjustment = win.ui.page_scrolls['display'].get_vadjustment()
    adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
    capture(win, 'ajr-connect-shortcuts')
    win.edit_keyboard_rule(0)
    editor = next(window for window in Gtk.Window.get_toplevels() if window.get_title() == 'Regra de teclado')
    capture(editor, 'ajr-connect-shortcut-editor')
    win.ui.toggle_theme()
    capture(editor, 'ajr-connect-shortcut-editor-dark')
    win.ui.toggle_theme()
    editor.set_default_size(360, 300)
    capture(editor, 'ajr-connect-shortcut-editor-minimum')
    editor.close()
    win.ui.show_page('sharing')
    capture(win, 'ajr-connect-sharing')
    win.cfg['shares'] = [dict(name='Projetos', path=str(Path.home() / 'Projetos')),
                         dict(name='Equipe', path=str(Path.home() / 'Documentos da equipe' /
                             ('Departamento com um nome longo ' * 4) / 'Relatórios'))]
    win.render_shares()
    assert not win.ui.empty_share_state.get_visible()
    capture(win, 'ajr-connect-sharing-folders')
    win.edit_share(0)
    folder_editor = next(window for window in Gtk.Window.get_toplevels()
                         if window.get_title() == 'Pasta compartilhada')
    capture(folder_editor, 'ajr-connect-share-editor')
    win.ui.toggle_theme()
    capture(folder_editor, 'ajr-connect-share-editor-dark')
    win.ui.toggle_theme()
    folder_editor.close()
    win.cfg['shares'] = []
    win.render_shares()
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
    win.set_default_size(620, 480)
    drain(.4)
    assert (win.get_surface().get_width(), win.get_surface().get_height()) == (620, 480), \
        ('Minimum window grew to fit content', win.get_surface().get_width(), win.get_surface().get_height())
    for page in ('connection', 'display', 'sharing'):
        win.ui.show_page(page)
        capture(win, 'ajr-connect-minimum-' + page)
    add = win.ui.empty_share_state.get_last_child()
    ok, action = add.compute_bounds(win)
    ok_view, viewport = win.form.compute_bounds(win)
    assert ok and ok_view and action.get_y() >= viewport.get_y()
    assert action.get_y() + action.get_height() <= viewport.get_y() + viewport.get_height(), \
        'Empty-state action hidden in minimum window'
    win.ui.toggle_theme()
    for page in ('connection', 'display', 'sharing'):
        win.ui.show_page(page)
        capture(win, 'ajr-connect-minimum-light-' + page)
    win.ui.toggle_theme()
    win.ui.show_page('connection')
    win.password.grab_focus()
    drain()
    ok, field = win.password.compute_bounds(win)
    ok_view, viewport = win.form.compute_bounds(win)
    assert ok and ok_view and field.get_y() >= viewport.get_y()
    assert field.get_y() + field.get_height() <= viewport.get_y() + viewport.get_height(), \
        'Focused password hidden behind the toolbar'
    capture(win, 'ajr-connect-minimum-password')
    win.show_error('Não foi possível conectar. Confira o endereço, o usuário e a senha para tentar novamente.')
    assert win.get_focus() == win.error, 'Error did not receive accessible focus'
    capture(win, 'ajr-connect-error')
    win.show_error('')
    win.form.set_sensitive(False)
    win.connect_btn.set_label('Desconectar')
    win.connect_btn.remove_css_class('suggested-action')
    win.controls.set_visible(True)
    win.set_status('Conectado · Tela cheia', 'marina em escritorio.example · HDMI-1',
                   'network-transmit-receive-symbolic')
    capture(win, 'ajr-connect-connected-compact')
    with patch.object(win, 'control') as command:
        child = win.controls.get_first_child()
        for expected in ('fullscreen', 'restore', 'minimize'):
            child.emit('clicked')
            command.assert_called_with(expected)
            child = child.get_next_sibling()
    win.controls.set_visible(False)
    win.form.set_sensitive(True)
    win.finish_connection()
    win.set_default_size(1120, 820)
    win.ui.show_page('connection')
    win.ui.toggle_theme()
    for page in ('connection', 'display', 'sharing'):
        win.ui.show_page(page)
        capture(win, 'ajr-connect-final-light-' + page)
    win.ui.toggle_theme()
    for page in ('connection', 'display', 'sharing'):
        win.ui.show_page(page)
        capture(win, 'ajr-connect-final-dark-' + page)
    win._bridge_ready = False
    win.portal_changed(False, 'Autorize o teclado do sistema para usar atalhos locais e remotos juntos.')
    capture(win, 'ajr-connect-keyboard-authorization')
    win.set_default_size(620, 480)
    win.ui.show_page('connection')
    capture(win, 'ajr-connect-keyboard-authorization-minimum')
    win.close()
    drain()
print('PASS: V2 light/dark, dialogs, folders, reconnecting, errors, session controls and '
      '1120×820 / 680×760 / 620×480 captures; no horizontal overflow or hidden primary actions')
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
                           env=env, check=True, timeout=55)
            subprocess.run([sys.executable, str(BASE / 'tests/check_keyboard_policy.py')],
                           env=env, check=True, timeout=30, stdout=subprocess.DEVNULL)
            for name, theme, width, scale in [('dark', 'dark', 800, 1), ('light', 'light', 800, 1),
                                             ('compact', 'dark', 400, 1), ('scale-2', 'dark', 1280, 2)]:
                bar_env = dict(env, AJR_BAR_THEME=theme, AJR_BAR_TEST_WIDTH=str(width), AJR_UI_SCALE=str(scale),
                               AJR_BAR_PREVIEW=str(args.output.resolve() / ('ajr-native-bar-' + name + '.png')))
                subprocess.run([str(BASE / 'tests/keyboard-policy')], env=bar_env, check=True,
                               timeout=10, stdout=subprocess.DEVNULL)
        finally:
            server.terminate()
            server.wait(timeout=5)
            server.stdout.close()


if __name__ == '__main__':
    main()
