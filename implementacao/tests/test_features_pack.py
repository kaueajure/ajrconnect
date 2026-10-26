"""Export/import, update channel migration, RTT helper and support report."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ajr_app
import core
from check_compatibility import collect_support_report
from tray import TrayController
from version import APP_VERSION


class FeaturesPackTests(unittest.TestCase):
    def test_export_import_roundtrip_without_password(self):
        cfg = copy.deepcopy(core.DEFAULT)
        cfg.update(server='lab.local', user='alice', quality=2, resolution='1080p')
        core.store_profile(cfg, 'Lab')
        payload = core.export_profiles(cfg)
        self.assertEqual(payload['format'], 'ajr-connect-profiles')
        self.assertNotIn('password', json.dumps(payload))
        other = copy.deepcopy(core.DEFAULT)
        other, count = core.import_profiles(other, payload)
        self.assertEqual(count, 1)
        self.assertEqual(other['profiles'][0]['server'], 'lab.local')
        self.assertEqual(other['profiles'][0]['quality'], 2)

    def test_import_assigns_new_id_on_collision(self):
        cfg = copy.deepcopy(core.DEFAULT)
        cfg.update(server='a', user='u')
        profile = core.store_profile(cfg, 'A')
        payload = core.export_profiles(cfg)
        cfg2 = copy.deepcopy(cfg)
        cfg2, count = core.import_profiles(cfg2, payload)
        self.assertEqual(count, 1)
        ids = [item['id'] for item in cfg2['profiles']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(profile['id'], ids)

    def test_update_channel_migration_and_save(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core, 'CFG_FILE', Path(folder) / 'config.json'):
            path = core.CFG_FILE
            path.write_text(json.dumps(dict(server='x', user='y', update_prereleases=False)))
            cfg = core.load_cfg()
            self.assertEqual(cfg['update_channel'], 'stable')
            self.assertFalse(cfg['update_prereleases'])
            cfg['update_channel'] = 'testing'
            core.save_cfg(cfg)
            restored = json.loads(path.read_text())
            self.assertEqual(restored['update_channel'], 'testing')
            self.assertTrue(restored['update_prereleases'])

    def test_measure_rtt_and_levels(self):
        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        with patch.object(ajr_app.socket, 'create_connection', return_value=Conn()):
            value = ajr_app.measure_rtt_ms('127.0.0.1:3389')
        self.assertGreaterEqual(value, 1)
        self.assertEqual(ajr_app.net_level(20), 0)
        self.assertEqual(ajr_app.net_level(120), 1)
        self.assertEqual(ajr_app.net_level(None), 2)

    def test_support_report_and_tray_dispose(self):
        text = collect_support_report(cfg=dict(appearance='dark', update_channel='testing',
                                               check_updates=True))
        self.assertIn(APP_VERSION, text)
        self.assertIn('Canal de atualização: testing', text)
        tray = TrayController(object())
        self.assertFalse(tray.available)
        tray.dispose()


if __name__ == '__main__':
    unittest.main()
