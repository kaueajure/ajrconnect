"""Consent, private tokens and balanced input without real desktop access."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gi.repository import Gio, GLib
from keyboard_portal import KeyboardPortal


class PortalBus:
    def __init__(self, response=0, devices=1, fail_key=None):
        self.response, self.devices, self.fail_key = response, devices, fail_key
        self.signals = {}
        self.calls = []
        self.events = []
        self.serial = 0

    def get_unique_name(self): return ':1.42'
    def signal_subscribe(self, _bus, interface, _signal, path, _arg, _flags, callback):
        self.serial += 1
        self.signals[self.serial] = (path, callback)
        return self.serial
    def signal_unsubscribe(self, serial): self.signals.pop(serial, None)
    def call(self, bus, path, interface, method, params, _out, _flags, _timeout, _cancel, callback):
        assert interface == ('org.freedesktop.portal.RemoteDesktop' if method != 'Close'
                             else 'org.freedesktop.portal.Request' if '/request/' in path
                             else 'org.freedesktop.portal.Session')
        values = params.unpack() if params else ()
        self.calls.append((method, values))
        if method == 'Close': return
        options = values[-1]
        request = '/org/freedesktop/portal/desktop/request/1_42/' + options['handle_token']
        result = {'session_handle': '/org/freedesktop/portal/desktop/session/1_42/test'} if method == 'CreateSession' else {}
        if method == 'Start': result = {'devices': self.devices, 'restore_token': 'next-private-token'}
        def respond():
            callback(self, SimpleNamespace(unpack=lambda: (request,)))
            for _serial, (signal_path, handler) in list(self.signals.items()):
                if signal_path == request:
                    handler(self, bus, request, interface, 'Response', GLib.Variant('(ua{sv})',
                        (self.response if method == 'Start' else 0,
                         {key: GLib.Variant('u' if key == 'devices' else 's', value) for key, value in result.items()})))
            return GLib.SOURCE_REMOVE
        GLib.idle_add(respond)
    def call_finish(self, result): return result
    def call_sync(self, _bus, _path, _interface, _method, params, *_args):
        assert _interface == 'org.freedesktop.portal.RemoteDesktop'
        _session, _options, key, state = params.unpack()
        if state and key == self.fail_key:
            raise GLib.Error.new_literal(Gio.io_error_quark(), 'Simulated denied input', 0)
        self.events.append((key, state))


class KeyboardPortalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.changes = []
        self.portal = KeyboardPortal(lambda ready, msg: self.changes.append((ready, msg)),
                                     Path(self.directory.name) / 'token.json')
        self.addCleanup(self.portal.close)

    def drain(self, predicate):
        import time
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            GLib.MainContext.default().iteration(False)
            time.sleep(.001)
        self.assertTrue(predicate(), 'Async operation did not complete')

    def start(self, bus):
        with patch.object(Gio, 'bus_get_sync', return_value=bus): self.portal.start()
        self.drain(lambda: not self.portal.pending)

    def test_keyboard_only_authorization_stores_private_rotated_token(self):
        self.portal.token_path.write_text('{"restore_token":"previous-token"}')
        bus = PortalBus()
        self.start(bus)
        self.assertTrue(self.portal.ready)
        options = next(values[-1] for name, values in bus.calls if name == 'SelectDevices')
        self.assertEqual((options['types'], options['persist_mode'], options['restore_token']), (1, 2, 'previous-token'))
        self.assertNotIn('SelectSources', [name for name, _ in bus.calls])
        self.assertIn('next-private-token', self.portal.token_path.read_text())
        self.assertEqual(self.portal.token_path.stat().st_mode & 0o777, 0o600)

    def test_cancel_and_pointer_only_permission_do_not_enable_keyboard(self):
        for bus in (PortalBus(response=1), PortalBus(devices=2)):
            self.start(bus)
            self.assertFalse(self.portal.ready)
            self.assertFalse(self.portal.token_path.exists())
            self.assertFalse(bus.signals)

    def test_repeated_start_opens_one_dialog_and_notifies_all_callers(self):
        bus, completed = PortalBus(), []
        with patch.object(Gio, 'bus_get_sync', return_value=bus):
            self.portal.start(lambda *args: completed.append(args))
            self.portal.start(lambda *args: completed.append(args))
        self.drain(lambda: len(completed) == 2)
        self.assertEqual([name for name, _ in bus.calls].count('Start'), 1)

    def test_key_replay_releases_every_modifier(self):
        bus = PortalBus()
        self.start(bus)
        completed = []
        self.portal.send(65363, 13, lambda *args: completed.append(args))
        self.drain(lambda: bool(completed))
        self.assertEqual(completed, [(True, '')])
        self.assertEqual(bus.events, [(65507, 1), (65513, 1), (65505, 1), (65363, 1),
                                      (65363, 0), (65505, 0), (65513, 0), (65507, 0)])

    def test_failed_replay_releases_keys_already_pressed(self):
        bus = PortalBus(fail_key=65363)
        self.start(bus)
        completed = []
        self.portal.send(65363, 12, lambda *args: completed.append(args))
        self.drain(lambda: bool(completed))
        self.assertFalse(completed[0][0])
        self.assertEqual(bus.events, [(65507, 1), (65513, 1), (65513, 0), (65507, 0)])

    def test_close_cancels_pending_requests_and_ignores_late_response(self):
        bus = PortalBus()
        with patch.object(Gio, 'bus_get_sync', return_value=bus): self.portal.start()
        self.portal.close()
        while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
        self.assertFalse(self.portal.ready)
        self.assertFalse(bus.signals)
        self.assertTrue(any(name == 'Close' for name, _ in bus.calls))


if __name__ == '__main__': unittest.main()
