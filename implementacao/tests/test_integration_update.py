"""Stable-loader updates and activation decisions, without changing the desktop."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import integration


class IntegrationFilesTests(unittest.TestCase):
    def test_updates_use_new_modules_and_keep_loader_and_previous_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'installed'
            shutil.copytree(BASE / 'extensao', source)
            first, changed = integration.install_extension(source, target)
            self.assertTrue(changed)
            previous = (target / first['module']).read_bytes()
            loader_mtime = (target / 'extension.js').stat().st_mtime_ns
            repeat, changed = integration.install_extension(source, target)
            self.assertFalse(changed)
            self.assertEqual(repeat, first)
            self.assertEqual((target / 'extension.js').stat().st_mtime_ns, loader_mtime)
            with (source / 'integration.js').open('a') as stream:
                stream.write('\n// next runtime\n')
            second, changed = integration.install_extension(source, target)
            self.assertFalse(changed)
            self.assertNotEqual(second['module'], first['module'])
            self.assertEqual((target / first['module']).read_bytes(), previous)
            self.assertEqual(json.loads((target / 'bridge.json').read_text()), second)
            self.assertEqual((target / 'extension.js').stat().st_mtime_ns, loader_mtime)

    def test_stylesheet_changes_get_a_new_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'installed'
            shutil.copytree(BASE / 'extensao', source)
            first, _ = integration.install_extension(source, target)
            with (source / 'stylesheet.css').open('a') as stream:
                stream.write('\n.ajr-brand { font-weight: normal; }\n')
            second, changed = integration.install_extension(source, target)
            self.assertFalse(changed)
            self.assertEqual(first['module'], second['module'])
            self.assertNotEqual(first['revision'], second['revision'])
            self.assertNotEqual(first['stylesheet'], second['stylesheet'])


class IntegrationActivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from gi.repository import Gio, GLib
        except ImportError:
            raise unittest.SkipTest('PyGObject indisponível.')
        cls.Gio, cls.GLib = Gio, GLib

    def fake_bus(self, revision='old', version=8, enabled=True, reject_reload=False, discovered=True):
        calls = []
        def call(_name, _path, interface, method, *_args):
            nonlocal revision, enabled
            calls.append(method)
            if interface == 'org.freedesktop.DBus.Peer':
                value = None
            elif method == 'GetExtensionInfo':
                value = dict(version=version, state=1 if enabled else 2) if discovered else {}
            elif method == 'EnableExtension':
                enabled, value = True, True
            elif enabled and method == 'GetRevision':
                value = revision
            elif enabled and method == 'Reload' and not reject_reload:
                revision, value = 'new', 'new'
            else:
                raise self.GLib.Error.new_literal(self.Gio.io_error_quark(), 'Unavailable', 0)
            return SimpleNamespace(unpack=lambda: (value,))
        return SimpleNamespace(call_sync=call), calls

    def test_current_revision_needs_no_toggle_or_reload(self):
        bus, calls = self.fake_bus(revision='new')
        with patch.object(self.Gio, 'bus_get_sync', return_value=bus):
            self.assertEqual(integration.refresh_integration('new'), 'ready')
        self.assertEqual(calls, ['Ping', 'GetRevision'])

    def test_runtime_update_reloads_without_toggling_extension(self):
        bus, calls = self.fake_bus()
        with patch.object(self.Gio, 'bus_get_sync', return_value=bus):
            self.assertEqual(integration.refresh_integration('new'), 'ready')
        self.assertEqual(calls, ['Ping', 'GetRevision', 'Reload'])

    def test_inactive_bridge_can_be_enabled_without_logout(self):
        bus, calls = self.fake_bus(enabled=False)
        with patch.object(self.Gio, 'bus_get_sync', return_value=bus):
            self.assertEqual(integration.refresh_integration('new'), 'ready')
        self.assertIn('EnableExtension', calls)
        self.assertNotIn('DisableExtension', calls)

    def test_legacy_extension_requires_migration_but_is_not_disabled(self):
        bus, calls = self.fake_bus(version=6, enabled=False)
        with patch.object(self.Gio, 'bus_get_sync', return_value=bus):
            self.assertEqual(integration.refresh_integration('new'), 'restart-required')
        self.assertNotIn('EnableExtension', calls)
        self.assertNotIn('DisableExtension', calls)

    def test_failed_runtime_reload_does_not_request_logout(self):
        bus, _ = self.fake_bus(reject_reload=True)
        with patch.object(self.Gio, 'bus_get_sync', return_value=bus):
            self.assertEqual(integration.refresh_integration('new', timeout=0), 'failed')

    def test_not_discovered_is_distinguished_from_cached_legacy_extension(self):
        bus, calls = self.fake_bus(enabled=False, discovered=False)
        with patch.object(self.Gio, 'bus_get_sync', return_value=bus):
            self.assertEqual(integration.refresh_integration('new'), 'not-discovered')
        self.assertNotIn('EnableExtension', calls)

    def test_no_graphical_shell_does_not_request_logout(self):
        error = self.GLib.Error.new_literal(self.Gio.io_error_quark(), 'No session bus', 0)
        with patch.object(self.Gio, 'bus_get_sync', side_effect=error):
            self.assertEqual(integration.refresh_integration('new'), 'unavailable')


if __name__ == '__main__':
    unittest.main()
