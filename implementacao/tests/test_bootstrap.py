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

    def test_download_has_no_session_or_distribution_gate(self):
        text = SCRIPT.read_text()
        for forbidden in ('/etc/os-release', 'gnome-shell --version', 'XDG_SESSION_TYPE'):
            self.assertNotIn(forbidden, text)

    def test_unsupported_architecture_stops_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'uname'
            binary.write_text('#!/bin/sh\nif [ "$1" = "-s" ]; then echo Linux; else echo aarch64; fi\n')
            binary.chmod(0o755)
            result = subprocess.run(['bash', str(SCRIPT)], capture_output=True, text=True,
                    env=dict(os.environ, PATH=directory + ':' + os.environ['PATH']), timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn('aarch64', result.stderr)
        self.assertIn('fontes', result.stderr)
        self.assertNotIn('baixando', result.stdout)

    def test_python_bootstrap_reports_apt_signature_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            sudo = Path(directory) / 'sudo'
            sudo.write_text('#!/bin/sh\necho "https://deb.anydesk.com NO_PUBKEY A2FB21D5A8772835" >&2\nexit 100\n')
            sudo.chmod(0o755)
            helper = Path(directory) / 'helper.sh'
            helper.write_text(SCRIPT.read_text().rsplit('ajr_main "$@"', 1)[0] +
                              '\najr_apt --yes install python3\n')
            result = subprocess.run(['bash', str(helper)], capture_output=True, text=True,
                    env=dict(os.environ, PATH=directory + ':' + os.environ['PATH']), timeout=5)
        self.assertEqual(result.returncode, 100)
        self.assertIn('assinatura/chave GPG', result.stderr)
        self.assertIn('https://deb.anydesk.com/howto.html', result.stderr)

    def test_python_bootstrap_does_not_update_package_lists(self):
        self.assertNotIn('ajr_apt update', SCRIPT.read_text())

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
