"""Retry decisions and isolated GTK recovery, without a real VM or keyring."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core
from reconnect import RetryPlan
import test_preferences as gui_harness


class RetryPolicyTests(unittest.TestCase):
    def test_bounded_backoff_cancel_and_reset(self):
        plan = RetryPlan()
        self.assertEqual([plan.next_delay() for _ in range(6)], [2, 4, 8, 16, 30, None])
        plan.reset()
        self.assertEqual(plan.next_delay(), 2)
        plan.cancel()
        self.assertIsNone(plan.next_delay())

    def test_only_network_failures_after_an_established_session_retry(self):
        plan = RetryPlan()
        for code in (131, 137, 139, 140, 141, 147):
            self.assertFalse(plan.should_retry(code))
            self.assertTrue(plan.should_retry(code, connected=True))
            self.assertTrue(plan.should_retry(code, recovering=True))
        for code in (0, 1, 2, 3, 11, 12, 132, 134, 135, 143, 145, 154, 155, -15):
            self.assertFalse(plan.should_retry(code, connected=True, recovering=True))
        self.assertFalse(RetryPlan(enabled=False).should_retry(131, connected=True))

    def test_reconnect_preferences_follow_profiles_and_updates_are_global(self):
        cfg = copy.deepcopy(core.DEFAULT)
        first = core.store_profile(cfg, 'First')['id']
        cfg.update(active_profile='', auto_reconnect=False, check_updates=False)
        second = core.store_profile(cfg, 'Second')['id']
        core.select_profile(cfg, first)
        self.assertTrue(cfg['auto_reconnect'])
        self.assertFalse(cfg['check_updates'])
        self.assertNotIn('check_updates', cfg['profiles'][0])
        core.select_profile(cfg, second)
        self.assertFalse(cfg['auto_reconnect'])


GUI_SCRIPT = r'''
import contextlib, io, sys, threading, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import ajr_app as gui
from gi.repository import Gio, GLib
from core import CFG_FILE

def drain(duration=.2):
    until = time.monotonic() + duration
    while time.monotonic() < until:
        while GLib.MainContext.default().pending() and time.monotonic() < until:
            GLib.MainContext.default().iteration(False)
        time.sleep(.005)

processes = []
ready = True
class Input(io.StringIO):
    def close(self): self.saved = self.getvalue(); super().close()
class Proc:
    def __init__(self, command, **kwargs):
        self.pid = 20000 + len(processes)
        self.stdin, self.code, self.ready = Input(), None, ready
        self.command = command
        processes.append(self)
    def poll(self): return self.code
    def terminate(self): self.code = -15
    def kill(self): self.code = -9
    def wait(self, **kwargs): return self.code
class X11:
    def close(self): pass
    def state(self, pid):
        proc = next(p for p in processes if p.pid == pid)
        return [0, 1, 0, 1, 600, 400, 1920, 1080] if proc.ready else None
    def find_window(self, pid): return None
    def control(self, pid, token, command):
        if command == 4: next(p for p in processes if p.pid == pid).code = 11
app = gui.App()
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
monitors = [dict(id='0', connector='HDMI-1', width=1920, height=1080, x=0, y=0, primary=True)]
with patch.object(gui, 'secret', return_value=''), patch.object(gui, 'X11', X11), \
        patch.object(gui, 'detect_monitors', return_value=monitors), \
        patch.object(gui, 'NATIVE', Path(sys.argv[1]) / 'core.py'), \
        patch.object(gui.subprocess, 'Popen', side_effect=Proc), \
        patch.object(gui.socket, 'create_connection', return_value=contextlib.nullcontext()):
    win = gui.MainWindow(app)
    win.present()
    win.server.set_text('test.example')
    win.user.set_text('example')
    win.keyboard_mode.set_selected(2)
    def connect():
        win.password.set_text('memory-only-password')
        win.do_connect()
        drain(.35)
        assert win._started and win.proc is not None
        assert not win.password.get_text()
        assert win._connection_request['password'] == 'memory-only-password'
        return win.proc

    # Network drop: progress and cancellation restore all controls and clear secrets.
    proc = connect()
    proc.code = 131
    win.poll_session()
    assert win._retry_source and win._reconnecting
    assert not win.form.get_sensitive() and win.connect_btn.get_sensitive()
    assert win.connect_btn.get_label() == 'Cancelar reconexão'
    assert win.status.title.get_text().startswith('Reconectando em')
    win.do_connect()
    assert not win.connection_busy() and win.form.get_sensitive()
    assert win._connection_request is None

    # Recover with the original password and fullscreen state; retry counter resets.
    proc = connect()
    win._retry_plan.delays = (.03,) * 5
    proc.code = 131
    win.poll_session()
    drain(.5)
    assert win.proc is not proc and win._started and not win._reconnecting
    assert win.proc.stdin.saved == 'memory-only-password\n'
    assert win.session['start_fullscreen'] is True
    assert win._retry_plan.attempts == 0
    win.do_connect()
    win.poll_session()
    assert not win.connection_busy() and win._connection_request is None

    # Network remains down: exactly five bounded retries, then editable UI.
    proc = connect()
    win._retry_plan.delays = (.01,) * 5
    with patch.object(gui.socket, 'create_connection', side_effect=OSError('offline')) as probe:
        proc.code = 131
        win.poll_session()
        drain(.6)
        assert probe.call_count == 5, probe.call_count
        assert not win.connection_busy() and win.form.get_sensitive()
        assert win._connection_request is None and '5 tentativas' in win.error.get_text()

    # Authentication rejection during recovery never retries again.
    proc = connect()
    win._retry_plan.delays = (.02,) * 5
    ready = False
    proc.code = 131
    win.poll_session()
    drain(.15)
    assert win.proc is not None and not win._started
    win.proc.code = 132
    win.poll_session()
    assert not win.connection_busy() and win._connection_request is None
    ready = True

    # An explicit opt-out and a normal server logoff do not reconnect.
    win.auto_reconnect.set_active(False)
    proc = connect()
    proc.code = 131
    win.poll_session()
    assert not win.connection_busy()
    win.auto_reconnect.set_active(True)
    proc = connect()
    proc.code = 2
    win.poll_session()
    assert not win.connection_busy() and not win.error.get_visible()

    # Cancellation during a slow probe ignores its late completion.
    entered, release = threading.Event(), threading.Event()
    def slow_probe(*args, **kwargs):
        entered.set()
        release.wait(2)
        return contextlib.nullcontext()
    count = len(processes)
    with patch.object(gui.socket, 'create_connection', side_effect=slow_probe):
        win.password.set_text('memory-only-password')
        win.do_connect()
        assert entered.wait(1)
        win.do_connect()
        assert not win.connection_busy()
        release.set()
        drain(.25)
        assert len(processes) == count and win.proc is None
        assert win.form.get_sensitive()
    for log in gui.DATA_DIR.glob('session-*.log'):
        assert 'memory-only-password' not in log.read_text()
    assert 'memory-only-password' not in CFG_FILE.read_text()
    win.close()
    drain()
print('PASS GTK recovery: reconnect/cancel, five failures, credential rejection, opt-out/logoff and stale worker')
'''


class GtkReconnectTests(unittest.TestCase):
    def test_recovery_on_private_display(self):
        gui_harness.GtkPreferencesTests.run_gui_script(self, GUI_SCRIPT)


if __name__ == '__main__':
    unittest.main()
