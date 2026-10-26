"""Resolution persistence and real FreeRDP negotiation flags, without a VM."""
import copy
import ctypes
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core

MONITOR = dict(id='0', connector='HDMI-1', x=1920, y=0, width=1920, height=1080)


class DisplayTests(unittest.TestCase):
    def test_every_resolution_is_sent_to_windows_and_viewport_stays_on_monitor(self):
        for resolution, _label, size in core.RESOLUTIONS:
            with self.subTest(resolution=resolution):
                cfg = copy.deepcopy(core.DEFAULT)
                cfg['resolution'] = resolution
                width, height = size or (1920, 1080)
                command = core.build_command(cfg, MONITOR)
                self.assertIn(f'/w:{width}', command)
                self.assertIn(f'/h:{height}', command)
                x, y, w, h = core.window_geometry(MONITOR, (width, height))
                self.assertGreaterEqual(x, MONITOR['x'])
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + w, MONITOR['x'] + MONITOR['width'])
                self.assertLessEqual(y + h, MONITOR['height'])
                self.assertAlmostEqual(w / h, width / height, delta=.01)

    def test_resolution_and_ram_preferences_follow_profiles_and_restart(self):
        cfg = copy.deepcopy(core.DEFAULT)
        cfg.update(resolution='4k', ram_alert=True, ram_limit_gib=3.5)
        first = core.store_profile(cfg, '4K')['id']
        cfg.update(active_profile='', resolution='720p', ram_alert=False, ram_limit_gib=2)
        second = core.store_profile(cfg, '720p')['id']
        core.select_profile(cfg, first)
        with tempfile.TemporaryDirectory() as folder, patch.object(core, 'CFG_FILE', Path(folder) / 'config.json'):
            core.save_cfg(cfg)
            restored = core.load_cfg()
        self.assertEqual((restored['resolution'], restored['ram_alert'], restored['ram_limit_gib']), ('4k', True, 3.5))
        core.select_profile(restored, second)
        self.assertEqual((restored['resolution'], restored['ram_alert']), ('720p', False))

    def test_invalid_and_legacy_settings_have_safe_defaults(self):
        for data in ({}, dict(resolution=['4k'], ram_alert='yes', ram_limit_gib=float('nan')),
                     dict(resolution='invalid', ram_limit_gib=-1), dict(ram_limit_gib=float('inf'))):
            cfg = core.normalize_settings(data)
            self.assertEqual(cfg['resolution'], 'monitor')
            self.assertFalse(cfg['ram_alert'])
            self.assertEqual(cfg['ram_limit_gib'], 4)

    def test_quality_presets_map_casa_4k_lab(self):
        self.assertEqual([item[1] for item in core.QUALITY_PRESETS], ['Casa', '4K', 'Lab'])
        self.assertEqual([item[2] for item in core.QUALITY_PRESETS], ['monitor', '4k', '1080p'])
        for quality, _label, resolution in core.QUALITY_PRESETS:
            cfg = copy.deepcopy(core.DEFAULT)
            cfg.update(quality=quality, resolution=resolution)
            command = core.build_command(cfg, MONITOR)
            self.assertIn('/gfx:rfx', command)
            if quality == 1:
                self.assertIn('+menu-anims', command)
            else:
                self.assertIn('-menu-anims', command)
            if quality == 2:
                self.assertIn('-window-drag', command)
            else:
                self.assertIn('+window-drag', command)

    def test_monitor_share_name_collision_is_rejected(self):
        cfg = copy.deepcopy(core.DEFAULT)
        cfg.update(ram_alert=True, shares=[dict(name='ajrmonitor', path='/tmp')])
        with self.assertRaisesRegex(ValueError, 'reservado'):
            core.build_command(cfg, MONITOR)

    def test_actual_freerdp_parser_preserves_visuals_with_rfx_gfx(self):
        try:
            rdp = ctypes.CDLL('libfreerdp2.so.2')
            client = ctypes.CDLL('libfreerdp-client2.so.2')
        except OSError as error:
            self.skipTest(str(error))
        rdp.freerdp_settings_new.argtypes = [ctypes.c_uint32]
        rdp.freerdp_settings_new.restype = ctypes.c_void_p
        rdp.freerdp_settings_free.argtypes = [ctypes.c_void_p]
        rdp.freerdp_settings_get_bool.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        rdp.freerdp_settings_get_uint32.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        rdp.freerdp_settings_get_uint32.restype = ctypes.c_uint32
        client.freerdp_client_settings_parse_command_line_arguments.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p), ctypes.c_int]
        for quality in range(3):
            cfg = copy.deepcopy(core.DEFAULT)
            cfg.update(server='example.invalid', user='test', quality=quality, resolution='4k')
            command = [value for value in core.build_command(cfg, MONITOR) if value != '/from-stdin:force']
            command.append('/p:isolated-test')
            argv = (ctypes.c_char_p * len(command))(*[value.encode() for value in command])
            settings = rdp.freerdp_settings_new(0)
            try:
                self.assertEqual(client.freerdp_client_settings_parse_command_line_arguments(
                    settings, len(command), argv, 0), 0)
                for name, key, expected in [('wallpaper', 962, False), ('themes', 965, False),
                    ('fonts', 961, True), ('composition', 968, False), ('gfx', 142, True),
                    ('rfx', 3649, True), ('menu', 964, quality != 1), ('drag', 963, quality == 2)]:
                    with self.subTest(quality=quality, setting=name):
                        self.assertEqual(bool(rdp.freerdp_settings_get_bool(settings, key)), expected)
                self.assertIn('/gfx:rfx', command)
                self.assertIn('/gdi:sw', command)
                self.assertEqual(rdp.freerdp_settings_get_uint32(settings, 131), 32)
                self.assertEqual(rdp.freerdp_settings_get_uint32(settings, 129), 3840)
                self.assertEqual(rdp.freerdp_settings_get_uint32(settings, 130), 2160)
            finally:
                rdp.freerdp_settings_free(settings)
