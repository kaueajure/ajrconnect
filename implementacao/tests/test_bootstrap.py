"""Ensure the download helper stops before installation on invalid inputs."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'docs/install.sh'


@unittest.skipUnless(SCRIPT.exists(), 'Download helper is in the repository docs directory')
class BootstrapTests(unittest.TestCase):
    def test_help_without_graphical_session(self):
        result = subprocess.run(['bash', str(SCRIPT), '--help'], capture_output=True, text=True,
                                env=dict(os.environ, XDG_SESSION_TYPE=''), timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertIn('--check', result.stdout)

    def test_download_has_no_session_architecture_or_distribution_gate(self):
        text = SCRIPT.read_text()
        for forbidden in ('/etc/os-release', 'uname -', 'gnome-shell --version', 'XDG_SESSION_TYPE'):
            self.assertNotIn(forbidden, text)

    def test_root_stops_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'id'
            binary.write_text('#!/bin/sh\nprintf "0\\n"\n')
            binary.chmod(0o755)
            env = dict(os.environ, PATH=directory + ':' + os.environ['PATH'])
            result = subprocess.run(['bash', str(SCRIPT)], capture_output=True, text=True,
                                    env=env, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn('sem sudo', result.stderr)
        self.assertNotIn('baixando', result.stdout)

    def test_corrupted_download_never_runs_python(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            curl = root / 'curl'
            curl.write_text('''#!/bin/sh
while [ "$#" -gt 0 ]; do
    if [ "$1" = '-o' ]; then shift; printf 'invalid archive' > "$1"; exit 0; fi
    shift
done
exit 1
''')
            python = root / 'python3'
            python.write_text('#!/bin/sh\ntouch "$AJR_TEST_MARKER"\nexit 0\n')
            curl.chmod(0o755)
            python.chmod(0o755)
            marker = root / 'python-ran'
            env = dict(os.environ, PATH=directory + ':' + os.environ['PATH'],
                       XDG_SESSION_TYPE='wayland', DISPLAY=':0', WAYLAND_DISPLAY='wayland-0',
                       TMPDIR=directory, AJR_TEST_MARKER=str(marker))
            result = subprocess.run(['bash', str(SCRIPT)], capture_output=True, text=True,
                                    env=env, timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertIn('integridade', result.stderr)
            self.assertFalse(marker.exists())
            self.assertEqual(list(root.glob('ajr-connect.*')), [])


if __name__ == '__main__':
    unittest.main()
