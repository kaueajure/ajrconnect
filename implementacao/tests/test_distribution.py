"""Test new-user defaults and installer files in an isolated home directory."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(os.environ.get('AJR_TEST_PACKAGE_ROOT', str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(BASE))
import core
import install


SANDBOX = '''
from pathlib import Path
import os, runpy, sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import install
home = Path.home()
cfg = home / '.config/ajr-connect/config.json'
cfg.parent.mkdir(parents=True)
original = b'{"server":"rdp.example.test:3389","user":"example","shares":[{"name":"Docs","path":"/example/docs"}]}'
cfg.write_bytes(original)
desktop = home / '.local/share/applications/ajr-connect.desktop'
old_desktop = b'[Desktop Entry]\\nType=Application\\nName=Previous AJR\\nExec=/bin/true\\n'
if sys.argv[2] == 'existing':
    desktop.parent.mkdir(parents=True)
    desktop.write_bytes(old_desktop)
with patch('subprocess.run'):
    assert install.install_files() == 0
    assert cfg.read_bytes() == original
    assert (home / '.local/bin/ajr-connect').is_file()
    assert '@AJR_LAUNCHER@' not in desktop.read_text()
    assert install.desktop_exec(home / '.local/bin/ajr-connect') in desktop.read_text()
    assert install.desktop_exec(sys.executable, install.APP / 'enable-extension.py') in (
        home / '.config/autostart/ajr-connect-integration.desktop').read_text()
    from gi.repository import Gio
    assert Gio.DesktopAppInfo.new_from_filename(str(desktop)) is not None
    if (Path(sys.argv[1]) / 'licenses').is_dir():
        assert (install.APP / 'licenses/Apache-2.0.txt').is_file()
    runpy.run_path(str(Path(sys.argv[1]) / 'rollback.py'))
assert cfg.read_bytes() == original
assert not (home / '.local/bin/ajr-connect').exists()
if sys.argv[2] == 'existing':
    assert desktop.read_bytes() == old_desktop
else:
    assert not desktop.exists()
'''


class DistributionTests(unittest.TestCase):
    def test_new_user_starts_without_personal_data(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(core, 'CFG_FILE', Path(directory) / 'missing.json'):
            cfg = core.load_cfg()
        self.assertEqual((cfg['server'], cfg['user'], cfg['shares']), ('', '', []))

    def test_existing_configuration_overrides_clean_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg_file = Path(directory) / 'config.json'
            cfg_file.write_text('{"server":"rdp.example.test","user":"example",'
                                '"shares":[{"name":"Docs","path":"/example/docs"}]}')
            with patch.object(core, 'CFG_FILE', cfg_file):
                cfg = core.load_cfg()
        self.assertEqual(cfg['server'], 'rdp.example.test')
        self.assertEqual(cfg['user'], 'example')
        self.assertEqual(cfg['shares'][0]['name'], 'Docs')

    def test_exec_rejects_newlines(self):
        with self.assertRaises(ValueError):
            install.desktop_exec('/example/invalid\npath')

    def test_installer_and_rollback_without_real_settings(self):
        for state in ('fresh', 'existing'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                home = Path(directory) / 'Pessoa AJR $ % " \\'
                home.mkdir()
                env = dict(os.environ, HOME=str(home), GSETTINGS_BACKEND='memory',
                           XDG_CONFIG_HOME=str(home / '.config'),
                           XDG_DATA_HOME=str(home / '.local/share'),
                           XDG_CACHE_HOME=str(home / '.cache'))
                result = subprocess.run([sys.executable, '-c', SANDBOX, str(BASE), state],
                                        env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
