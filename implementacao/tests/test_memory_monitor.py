"""Guest sample validation, threshold decisions and isolated GTK warning actions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memory_monitor import GIB, MemoryMonitor, MemorySample


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 0
        self.monitor = MemoryMonitor(self.folder.name, 'test-session', 2, clock=lambda: self.now)

    def write_sample(self, **overrides):
        data = dict(session='test-session', sequence=1, used_bytes=GIB, total_bytes=4 * GIB)
        data.update(overrides)
        (Path(self.folder.name) / 'memory.json').write_text(json.dumps(data))

    def test_missing_corrupt_wrong_session_and_stale_are_unavailable(self):
        self.assertIsNone(self.monitor.read())
        for overrides in [dict(session='another'), dict(used_bytes=-1), dict(total_bytes=1),
                          dict(sequence=True), dict(used_bytes='1024')]:
            self.write_sample(**overrides)
            self.assertIsNone(self.monitor.read())
        self.write_sample()
        self.assertEqual(self.monitor.read(), MemorySample(GIB, 4 * GIB))
        self.now = 16
        self.assertIsNone(self.monitor.read())
        self.write_sample(sequence=2)
        self.assertIsNotNone(self.monitor.read())
        (Path(self.folder.name) / 'memory.json').write_text('{')
        self.assertIsNone(self.monitor.read())

    def test_symlinks_and_oversized_files_are_rejected(self):
        path = Path(self.folder.name) / 'memory.json'
        path.symlink_to('/etc/passwd')
        self.assertIsNone(self.monitor.read())
        path.unlink()
        path.write_text(' ' * 4097)
        self.assertIsNone(self.monitor.read())

    def test_continue_suppresses_duplicates_until_usage_returns_below_limit(self):
        high = MemorySample(3 * GIB, 4 * GIB)
        self.assertTrue(self.monitor.warning_needed(high))
        self.monitor.acknowledge()
        self.assertFalse(self.monitor.warning_needed(high))
        self.assertFalse(self.monitor.warning_needed(MemorySample(2 * GIB, 4 * GIB)))
        self.assertFalse(self.monitor.warning_needed(MemorySample(GIB, 4 * GIB)))
        self.assertTrue(self.monitor.warning_needed(high))

    def test_share_contains_only_session_scoped_guest_collector_and_is_cleaned(self):
        monitor = MemoryMonitor.create(self.folder.name, 4)
        self.assertEqual(monitor.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads((monitor.directory / 'session.json').read_text())['session'], monitor.session)
        collector = (monitor.directory / 'monitor.ps1').read_text()
        self.assertIn('Win32_OperatingSystem', collector)
        self.assertNotIn('__SESSION__', collector)
        self.assertIn(monitor.session, collector)
        self.assertIn('iniciar.cmd', [path.name for path in monitor.directory.iterdir()])
        monitor.close()
        self.assertFalse(monitor.directory.exists())


GUI_SCRIPT = r'''
import copy, sys, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import ajr_app as gui
from gi.repository import Gio, GLib
from memory_monitor import MemoryMonitor, MemorySample, GIB
from core import RESOLUTIONS
def drain():
    until = time.monotonic() + .15
    while time.monotonic() < until:
        while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
        time.sleep(.005)
app = gui.App(); app.set_flags(Gio.ApplicationFlags.NON_UNIQUE); app.register(None)
with patch.object(gui, 'secret', return_value=''), patch.object(gui, 'detect_monitors', return_value=[]), \
        patch.object(gui.socket, 'create_connection', side_effect=OSError('isolated')):
    win = gui.MainWindow(app)
    win.present()
    win.resolution.set_selected(1)
    win.ram_alert.set_active(True)
    win.ram_limit.set_value(2.5)
    win.persist()
    assert win.cfg['resolution'] == '4k' and win.cfg['ram_limit_gib'] == 2.5
    win.cfg.update(resolution='360p', ram_alert=False, ram_limit_gib=3)
    win.apply_profile()
    assert RESOLUTIONS[win.resolution.get_selected()][0] == '360p'
    assert not win.ram_limit.get_sensitive()
    monitor = MemoryMonitor.create(Path.home() / 'memory', 2)
    GLib.source_remove(win._poll)
    class Proc:
        pid = 42000
    win.proc = Proc()
    win._connection_request = dict(memory=monitor)
    win._started = True
    actions = []
    with patch.object(win, 'control', side_effect=actions.append), \
            patch.object(monitor, 'read', return_value=MemorySample(3 * GIB, 4 * GIB)):
        win.poll_memory()
        drain()
        assert actions == ['minimize'] and win._ram_dialog
        win._ram_dialog.response('continue'); drain()
        assert not win._ram_dialog and monitor.acknowledged
        win._ram_next_poll = 0; win.poll_memory(); assert not win._ram_dialog
        monitor.acknowledged = False
        win._ram_next_poll = 0; win.poll_memory()
        with patch.object(win, 'cancel_connection') as cancel:
            win._ram_dialog.response('stop'); drain()
            cancel.assert_called_once()
        monitor.acknowledged = False
        win._ram_next_poll = 0; win.poll_memory()
        with patch.object(win, 'cancel_connection') as cancel:
            stale_dialog = win._ram_dialog
            win.close_memory_dialogs(); stale_dialog.response('stop'); drain()
            cancel.assert_not_called()
    win.proc = None
    win.finish_connection()
    assert not monitor.directory.exists()
    win._poll = GLib.timeout_add(250, win.poll_session)
    win.close(); drain()
print('PASS RAM GTK: resolution/settings, warning, continue, stop, stale dialog and cleanup')
'''


class MemoryUITests(unittest.TestCase):
    def test_warning_actions(self):
        import test_preferences
        test_preferences.GtkPreferencesTests.run_gui_script(self, GUI_SCRIPT)
