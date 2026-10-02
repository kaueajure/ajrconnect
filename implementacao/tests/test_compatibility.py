"""Check installer boundaries without installing or changing the user's settings."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import check_compatibility as compatibility
import install


class CompatibilityTests(unittest.TestCase):
    def test_zorin_minor_version(self):
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / 'os-release'
            release.write_text('ID=zorin\nVERSION_ID="18"\nVERSION="18.1"\n')
            self.assertTrue(compatibility.supported_os(compatibility.read_os_release(release)))
        for values in ({'ID': 'zorin', 'VERSION': '18'},
                       {'ID': 'zorin', 'VERSION': '18.2'},
                       {'ID': 'ubuntu', 'VERSION': '18.1'}):
            self.assertFalse(compatibility.supported_os(values))

    def test_install_blocked_before_mutation(self):
        with patch.object(install, 'check_compatibility', return_value=False), \
                patch.object(install, 'install_files') as mutate:
            self.assertEqual(install.install(), 1)
            mutate.assert_not_called()

    def test_incomplete_package(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(compatibility, 'run', return_value=(True, '')):
            checks = compatibility.collect_checks(Path(directory))
        package = next(check for check in checks if check.name == 'Arquivos do pacote')
        self.assertFalse(package.ok)
        self.assertIn('native/ajr-freerdp', package.detail)

    def test_missing_python_gi_is_reported(self):
        def probe(command):
            if command[-1] == compatibility.GI_PROBE:
                return False, "ModuleNotFoundError: No module named 'gi'"
            return True, ''
        with patch.object(compatibility, 'run', side_effect=probe):
            check = next(item for item in compatibility.collect_checks()
                         if item.name == 'Interface Python')
        self.assertFalse(check.ok)
        self.assertIn('python3-gi', check.remedy)

    def test_winpr_mismatch_is_rejected(self):
        fake_libraries = '''
import ctypes
class FakeLibrary:
    def __init__(self, name): self.name = name
    def __getattr__(self, symbol):
        value = b'2.12.0' if 'winpr' in self.name else b'2.11.5'
        return lambda: value
ctypes.CDLL = FakeLibrary
'''
        ok, detail = compatibility.run([sys.executable, '-c',
                                         fake_libraries + compatibility.LIBRARY_PROBE])
        self.assertFalse(ok)
        self.assertIn('libwinpr2.so.2: 2.12.0', detail)

    def test_check_mode_fails_without_touching_home(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, HOME=directory, XDG_SESSION_TYPE='x11')
            result = subprocess.run([sys.executable, str(BASE / 'install.py'), '--check'],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('Instalação bloqueada', result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
