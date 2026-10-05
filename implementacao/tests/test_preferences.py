"""Profile migration and isolated GTK preference flows; no real VM or keyring."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import core


class ProfileTests(unittest.TestCase):
    def test_appearance_is_preserved_across_profiles_and_restart(self):
        cfg = copy.deepcopy(core.DEFAULT)
        cfg.update(server='one.example', user='first', appearance='light')
        first = core.store_profile(cfg, 'Primeiro')['id']
        cfg.update(active_profile='', server='two.example', user='second')
        core.store_profile(cfg, 'Segundo')
        core.select_profile(cfg, first)
        self.assertEqual(cfg['appearance'], 'light')
        self.assertNotIn('appearance', cfg['profiles'][0])
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(core, 'CFG_FILE', Path(directory) / 'config.json'):
                core.save_cfg(cfg)
                self.assertEqual(core.load_cfg()['appearance'], 'light')

    def test_legacy_profile_migrates_without_losing_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(dict(server='old.example', user='old', remember=True,
                capture_keyboard=False, shares=[dict(name='Docs', path='/tmp/docs')], password='discard')))
            with patch.object(core, 'CFG_FILE', path):
                cfg = core.load_cfg()
                self.assertEqual(cfg['keyboard_mode'], 'local')
                self.assertEqual(len(cfg['profiles']), 1)
                self.assertEqual(cfg['profiles'][0]['shares'], cfg['shares'])
                core.save_cfg(cfg)
                restored = core.load_cfg()
            self.assertEqual(restored['active_profile'], cfg['active_profile'])
            self.assertNotIn('password', path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_two_connections_have_independent_preferences(self):
        cfg = copy.deepcopy(core.DEFAULT)
        cfg.update(server='one.example', user='first', shares=[dict(name='A', path='/tmp/a')])
        first = core.store_profile(cfg, 'Primeiro')['id']
        cfg.update(active_profile='', server='two.example', user='second', shares=[],
                   fullscreen_shortcut='<Control><Shift>F12', remote_alt_tab=False)
        second = core.store_profile(cfg, 'Segundo')['id']
        core.select_profile(cfg, first)
        self.assertEqual((cfg['server'], cfg['user']), ('one.example', 'first'))
        self.assertTrue(cfg['remote_alt_tab'])
        cfg['shares'][0]['path'] = '/tmp/changed'
        self.assertEqual(cfg['profiles'][0]['shares'][0]['path'], '/tmp/a')
        core.select_profile(cfg, second)
        self.assertFalse(cfg['remote_alt_tab'])
        self.assertEqual(cfg['fullscreen_shortcut'], '<Control><Shift>F12')
        self.assertEqual(cfg['shares'], [])

    def test_malformed_profiles_are_ignored_and_secrets_are_filtered(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(dict(profiles=[None, {}, dict(id='same', name='A',
                server='one.example', password='never'), dict(id='same', name='Duplicate')],
                active_profile='missing', quality=None, keyboard_mode='invalid')))
            with patch.object(core, 'CFG_FILE', path):
                cfg = core.load_cfg()
                self.assertEqual(len(cfg['profiles']), 1)
                self.assertEqual(cfg['active_profile'], '')
                self.assertEqual(cfg['keyboard_mode'], 'fullscreen')
                cfg['profiles'][0]['password'] = 'never'
                core.save_cfg(cfg)
            self.assertNotIn('never', path.read_text())

    def test_local_mode_does_not_grab_and_shares_remain_arguments(self):
        cfg = copy.deepcopy(core.DEFAULT)
        cfg.update(server='one.example', user='first', keyboard_mode='local',
                   shares=[dict(name='Documentos', path='/tmp/Meu trabalho')])
        command = core.build_command(cfg, dict(id='0', x=0, y=0, width=1920, height=1080))
        self.assertIn('-grab-keyboard', command)
        self.assertIn('/drive:Documentos,/tmp/Meu trabalho', command)


GUI_SCRIPT = r'''
import sys, tempfile, time, threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import ajr_app as gui
from ajr_app import Gtk, Gdk, Gio, GLib, App, MainWindow, ShareEditor, ShortcutEditor

def drain(duration=0.15):
    end = time.monotonic() + duration
    while time.monotonic() < end:
        while GLib.MainContext.default().pending() and time.monotonic() < end:
            GLib.MainContext.default().iteration(False)
        time.sleep(.005)

app = App()
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
with patch.object(gui, 'secret', return_value=''), patch.object(gui, 'detect_monitors', return_value=[]), \
        patch.object(gui.socket, 'create_connection', side_effect=OSError('isolated test')):
    win = MainWindow(app)
    win.present()
    win.server.set_text('one.example')
    win.user.set_text('first')
    win.profile_name.set_text('Primeiro')
    win.password.set_text('test password')
    win.save_profile()
    first = win.cfg['active_profile']
    win.new_profile()
    assert not win.password.get_text()
    win.server.set_text('two.example')
    win.user.set_text('second')
    win.profile_name.set_text('Segundo')
    win.keyboard_rows['remote_alt_tab'].set_active(False)
    win.set_shortcut('<Control><Shift>F12')
    win.save_profile()
    second = win.cfg['active_profile']
    assert len(win.cfg['profiles']) == 2
    win.ui.search.set_text('two.example')
    drain(.25)
    assert win.ui.profile_list.get_first_child().profile_index == 1
    assert win.ui.profile_list.get_first_child().get_next_sibling() is None
    win.ui.search.set_text('no-match')
    drain(.25)
    assert win.ui.empty_profiles.get_visible()
    win.ui.search.set_text('')
    drain(.25)
    win.ui.show_page('display')
    assert win.form.get_visible_child_name() == 'display'
    win.ui.show_page('sharing')
    assert win.form.get_visible_child_name() == 'sharing'
    win.ui.toggle_theme()
    assert win.cfg['appearance'] == 'light'
    win.form.set_sensitive(False)
    assert not win.ui.profile_area.get_sensitive()
    assert not win.ui.compact_profiles.get_sensitive()
    win.form.set_sensitive(True)
    win.set_default_size(680, 760)
    drain(.3)
    assert win.ui.split.get_collapsed()
    assert win.ui.compact_profiles.get_visible()
    win.ui.show_page('connection')
    win.profile.set_selected(0)
    assert win.cfg['active_profile'] == first
    assert win.server.get_text() == 'one.example'
    assert win.keyboard_rows['remote_alt_tab'].get_active()
    assert win.cfg['fullscreen_shortcut'] == '<Control><Alt>Return'
    win.profile.set_selected(1)
    assert win.cfg['active_profile'] == second
    assert not win.keyboard_rows['remote_alt_tab'].get_active()
    assert Gtk.accelerator_parse(win.cfg['fullscreen_shortcut']) == Gtk.accelerator_parse('<Control><Shift>F12')
    win.keyboard_mode.set_selected(2)
    assert not win.keyboard_rows['remote_alt_tab'].get_sensitive()
    win.persist()
    assert win.cfg['capture_keyboard'] is False

    # A stale keyring completion must not fill credentials after identity changes.
    entered, release = threading.Event(), threading.Event()
    def delayed_secret(*args):
        entered.set()
        release.wait(2)
        return 'stale password'
    win.remember.set_active(True)
    with patch.object(gui, 'secret', side_effect=delayed_secret):
        win.lookup_password()
        assert entered.wait(2)
        win.server.set_text('changed.example')
        release.set()
        drain()
        assert not win.password.get_text()

    values = []
    editor = ShareEditor(win, {}, values.append)
    editor.present()
    editor.choose()
    drain()
    assert editor._chooser.get_visible()
    with tempfile.TemporaryDirectory(prefix='ajr pasta ') as folder:
        # Browse into a directory and choose its nested folder without typing it.
        nested = Path(folder) / 'Documentos da equipe'
        nested.mkdir()
        editor._chooser.set_current_folder(Gio.File.new_for_path(folder))
        drain()
        editor._chooser.set_file(Gio.File.new_for_path(str(nested)))
        drain()
        editor._chooser.response(Gtk.ResponseType.ACCEPT)
        assert editor._chooser is None
        assert editor.path.get_text() == str(nested)
        editor.save()
        assert values[0]['path'] == str(nested.resolve())
    editor = ShareEditor(win, {}, values.append)
    editor.choose()
    editor._chooser.response(Gtk.ResponseType.CANCEL)
    assert not editor.path.get_text()
    editor.close()

    recorded = []
    shortcut = ShortcutEditor(win, '<Control><Alt>Return', recorded.append)
    shortcut.key_pressed(None, Gdk.KEY_F11, 0, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
    shortcut.save()
    assert recorded == ['<Shift><Control>F11']
    # Failed connection restores the whole workspace, including the sidebar.
    fake_monitors = [dict(id='0', connector='HDMI-1', width=1920, height=1080, x=0, y=0, primary=True)]
    with patch.object(gui, 'detect_monitors', return_value=fake_monitors), \
            patch.object(gui, 'NATIVE', Path(sys.argv[1]) / 'core.py'):
        win.refresh_monitors()
        win.password.set_text('example password')
        win.do_connect()
        drain(.4)
        assert win.proc is None
        assert win.form.get_sensitive() and win.ui.profile_area.get_sensitive()
        assert win.connect_btn.get_label() == 'Conectar ao Windows'
        assert win.error.get_visible()
        assert not win.ui.spinner.get_spinning()
    win.delete_profile()
    dialog = next(w for w in Gtk.Window.get_toplevels() if isinstance(w, gui.Adw.MessageDialog))
    dialog.response('delete')
    assert len(win.cfg['profiles']) == 1
    assert win.cfg['active_profile'] == first
    win.close()
    drain()
print('PASS GTK: responsive navigation/search/themes, profiles, stale credentials, folders, shortcuts and delete')
'''


class GtkPreferencesTests(unittest.TestCase):
    def test_preferences_on_private_display(self):
        sdk = BASE / 'tests/tools/sdk'
        xvfb = shutil.which('Xvfb') or sdk / 'usr/bin/Xvfb'
        if not Path(xvfb).exists():
            self.skipTest('Xvfb indisponível; instale-o para executar os testes GTK isolados.')
        probe = subprocess.run([sys.executable, '-c', 'import gi'], capture_output=True)
        if probe.returncode:
            self.skipTest('PyGObject indisponível.')
        env = dict(os.environ, GDK_BACKEND='x11', GSK_RENDERER='cairo',
                   GSETTINGS_BACKEND='memory', DBUS_SESSION_BUS_ADDRESS='unix:path=/nonexistent',
                   LD_LIBRARY_PATH=str(sdk / 'usr/lib/x86_64-linux-gnu'))
        server = subprocess.Popen([str(xvfb), '-displayfd', '1', '-screen', '0', '1024x900x24',
            '-nolisten', 'tcp', '-noreset'], env=env, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True)
        try:
            env['DISPLAY'] = ':' + server.stdout.readline().strip()
            with tempfile.TemporaryDirectory() as directory:
                env.update(HOME=directory, XDG_CONFIG_HOME=directory + '/.config',
                           XDG_DATA_HOME=directory + '/.local/share', XDG_CACHE_HOME=directory + '/.cache')
                try:
                    result = subprocess.run([sys.executable, '-c', GUI_SCRIPT, str(BASE)],
                        env=env, capture_output=True, text=True, timeout=20)
                except subprocess.TimeoutExpired as exc:
                    self.fail('Timeout nos fluxos GTK: ' + str(exc.stdout) + str(exc.stderr))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        finally:
            server.terminate()
            server.wait(timeout=5)
            server.stdout.close()


if __name__ == '__main__':
    unittest.main()
