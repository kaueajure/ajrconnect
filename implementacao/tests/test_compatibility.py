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
    def test_session_and_distribution_are_not_checked(self):
        with patch.dict(os.environ, {'XDG_SESSION_TYPE': 'x11', 'XDG_CURRENT_DESKTOP': 'KDE',
                                    'DISPLAY': '', 'WAYLAND_DISPLAY': ''}):
            checks = compatibility.collect_checks()
        self.assertTrue(all(item.ok for item in checks))
        self.assertTrue(all(item.name not in ('Sistema', 'Sessão gráfica', 'GNOME ativo')
                            for item in checks))

    def test_wrong_architecture_blocks_before_dependencies(self):
        with patch.object(compatibility.platform, 'machine', return_value='aarch64'), \
                patch.object(install, 'ensure_dependencies') as dependencies, \
                patch.object(install, 'install_files') as mutate:
            self.assertEqual(install.install(), 1)
            dependencies.assert_not_called()
            mutate.assert_not_called()

    def test_native_loader_failure_is_reported(self):
        def probe(command):
            if command[0] == 'ldd':
                return False, "version `GLIBC_2.38' not found"
            return True, ''
        with patch.object(compatibility, 'run', side_effect=probe):
            check = next(item for item in compatibility.collect_checks()
                         if item.name == 'Bibliotecas do cliente')
        self.assertFalse(check.ok)
        self.assertIn('GLIBC_2.38', check.detail)

    def test_invalid_binary_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'native').mkdir()
            (base / 'native/ajr-freerdp').write_bytes(b'invalid binary')
            checks = compatibility.collect_package_checks(base)
        self.assertFalse(next(item for item in checks if item.name == 'Arquitetura do cliente').ok)

    def test_ldd_missing_library_with_zero_exit_status_is_rejected(self):
        def probe(command):
            return (True, 'libX11.so.6 => not found') if command[0] == 'ldd' else (True, '')
        with patch.object(compatibility, 'run', side_effect=probe):
            check = next(item for item in compatibility.collect_checks()
                         if item.name == 'Bibliotecas do cliente')
        self.assertFalse(check.ok)

    def test_install_blocked_before_mutation(self):
        with patch.object(install, 'check_compatibility', return_value=False), \
                patch.object(install, 'ensure_dependencies', return_value=True), \
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

    def test_check_mode_allows_no_session_without_touching_home(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, HOME=directory, XDG_SESSION_TYPE='', DISPLAY='', WAYLAND_DISPLAY='')
            result = subprocess.run([sys.executable, str(BASE / 'install.py'), '--check'],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Dependências disponíveis', result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
