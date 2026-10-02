"""Exercise dependency plans without sudo, network or system package changes."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dependencies as deps
import install


class DependencyTests(unittest.TestCase):
    def test_anydesk_signature_failure_reports_cause_and_remedy(self):
        output = ("Err:13 https://deb.anydesk.com all InRelease\n"
                  "NO_PUBKEY A2FB21D5A8772835\n"
                  "N: Skipping acquire of configured file 'main/binary-i386/Packages'\n")
        result = subprocess.CompletedProcess([], 100, output,
                    "E: The repository 'https://deb.anydesk.com all InRelease' is not signed.")
        with patch.object(deps.subprocess, 'run', return_value=result):
            with self.assertRaises(deps.DependencyError) as failure:
                deps.run(['sudo', 'apt-get', 'update'])
        message = str(failure.exception)
        for expected in ('sudo apt-get update', '100', 'NO_PUBKEY A2FB21D5A8772835',
                         'assinatura/chave GPG', 'https://deb.anydesk.com/howto.html'):
            self.assertIn(expected, message)

    def test_i386_notice_alone_does_not_block_apt(self):
        result = subprocess.CompletedProcess([], 0, '',
                    "N: Skipping acquire: repository doesn't support architecture 'i386'")
        with patch.object(deps.subprocess, 'run', return_value=result):
            deps.run(['sudo', 'apt-get', 'update'])

    def test_signature_warning_with_cached_indexes_still_blocks(self):
        result = subprocess.CompletedProcess([], 0, '',
                    'W: GPG error: https://deb.anydesk.com NO_PUBKEY A2FB21D5A8772835')
        with patch.object(deps.subprocess, 'run', return_value=result):
            with self.assertRaises(deps.DependencyError):
                deps.run(['sudo', 'apt-get', 'update'])

    def test_install_signature_error_is_explained_without_update(self):
        result = subprocess.CompletedProcess([], 100, '',
                    'E: https://deb.anydesk.com NO_PUBKEY A2FB21D5A8772835')
        with patch.object(deps.subprocess, 'run', return_value=result):
            with self.assertRaises(deps.DependencyError) as failure:
                deps.run(['sudo', 'apt-get', 'install', 'python3'])
        self.assertIn('https://deb.anydesk.com/howto.html', str(failure.exception))

    def test_network_failure_is_not_reported_as_signature_error(self):
        result = subprocess.CompletedProcess([], 100, '', 'Temporary failure resolving host')
        with patch.object(deps.subprocess, 'run', return_value=result):
            with self.assertRaises(deps.DependencyError) as failure:
                deps.run(['sudo', 'apt-get', 'update'])
        self.assertIn('Temporary failure resolving host', str(failure.exception))
        self.assertNotIn('assinatura/chave GPG', str(failure.exception))

    def plan(self, missing=(), candidate='2.11.5+dfsg1-1build2', failure=None):
        calls = []
        completed = [False]
        def version(package):
            logical = next((key for key, choices in deps.RDP_CHOICES.items() if package in choices), package)
            if logical in missing and not completed[0]:
                return None
            return '2.11.5+dfsg1-1build2' if logical in deps.RDP_PACKAGES else '1.0'
        def run(command, capture=True):
            calls.append(command)
            if failure and failure(command):
                raise deps.DependencyError('Simulated package manager failure')
            if command[:2] == ['apt-cache', 'policy']:
                value = candidate.get(command[-1], '(none)') if isinstance(candidate, dict) else candidate
                return '  Candidate: ' + value + '\n'
            if command[:2] == ['sudo', 'apt-get'] and 'install' in command:
                completed[0] = True
            return ''
        with patch.object(deps, 'validate_target'), \
                patch.object(deps, 'validate_existing_rdp'), \
                patch.object(deps, 'runtime_available', return_value=not missing), \
                patch.object(deps, 'installed_version', side_effect=version), \
                patch.object(deps, 'run', side_effect=run), \
                patch.object(deps.shutil, 'which', return_value='/usr/bin/sudo'):
            result = deps.ensure_dependencies()
        return result, calls

    def test_distribution_security_revisions(self):
        for version in ('2.11.5', '2.11.5+dfsg1-1build2', '1:2.11.5+dfsg1-1ubuntu0.1~esm6'):
            self.assertTrue(deps.compatible_rdp_version(version))
        for version in ('2.11.50', '2.12.0', '3.0.0', '(none)', ''):
            self.assertFalse(deps.compatible_rdp_version(version))

    def test_complete_environment_never_uses_sudo(self):
        result, calls = self.plan()
        self.assertTrue(result)
        self.assertEqual(calls, [])

    def test_installs_only_missing_and_pins_rdp_candidate(self):
        result, calls = self.plan(missing=('libsecret-tools', 'libfreerdp-client2-2t64'))
        self.assertTrue(result)
        transaction = next(command for command in calls if command[:2] == ['sudo', 'apt-get']
                           and 'install' in command)
        self.assertIn('libsecret-tools', transaction)
        self.assertIn('libfreerdp-client2-2t64=2.11.5+dfsg1-1build2', transaction)
        self.assertIn('--no-remove', transaction)
        self.assertFalse(any('update' in command for command in calls))
        self.assertNotIn('gnome-shell', transaction)
        self.assertNotIn('--allow-downgrades', transaction)
        simulation = next(command for command in calls if '--simulate' in command)
        self.assertLess(calls.index(simulation), calls.index(transaction))
        self.assertLess(calls.index(simulation), calls.index(['sudo', '-v']))

    def test_incompatible_candidate_stops_before_package_install(self):
        for version in ('3.0.0', '(none)'):
            with self.subTest(version=version):
                result, calls = self.plan(missing=('libfreerdp2-2t64',), candidate=version)
                self.assertFalse(result)
                self.assertFalse(any('install' in command for command in calls))

    def test_installed_incompatible_rdp_rejected_before_loading(self):
        installed = {package: '2.11.5' for package in deps.RDP_PACKAGES}
        installed['libwinpr2-2t64'] = '2.12.0'
        with patch.object(deps.ctypes, 'CDLL') as load:
            with self.assertRaises(deps.DependencyError):
                deps.validate_existing_rdp(installed)
            load.assert_not_called()

    def test_apt_failure_stops_transaction(self):
        for stage in ('--simulate', 'install'):
            with self.subTest(stage=stage):
                result, calls = self.plan(missing=('libsecret-tools',),
                                          failure=lambda command: stage in command)
                self.assertFalse(result)
                if stage != 'install':
                    self.assertFalse(any(command[:2] == ['sudo', 'apt-get'] and 'install' in command
                                         for command in calls))
                    self.assertNotIn(['sudo', '-v'], calls)

    def test_install_scope_has_no_desktop_or_distribution_gate(self):
        with patch.dict(deps.os.environ, {'XDG_CURRENT_DESKTOP': 'KDE', 'XDG_SESSION_TYPE': 'x11'}), \
                patch.object(deps.os, 'geteuid', return_value=1000), \
                patch.object(deps, 'run') as command:
            deps.validate_target()
            command.assert_not_called()

    def test_legacy_package_names_supported(self):
        result, calls = self.plan(missing=('libfreerdp2-2t64',),
                                  candidate={'libfreerdp2-2': '2.11.5+dfsg1-1'})
        self.assertTrue(result)
        transaction = next(command for command in calls if command[:2] == ['sudo', 'apt-get']
                           and 'install' in command)
        self.assertIn('libfreerdp2-2=2.11.5+dfsg1-1', transaction)

    def test_available_runtime_does_not_require_apt(self):
        with patch.object(deps, 'validate_target'), \
                patch.object(deps, 'installed_version', return_value=None), \
                patch.object(deps, 'validate_existing_rdp'), \
                patch.object(deps, 'runtime_available', return_value=True), \
                patch.object(deps.shutil, 'which', return_value=None), \
                patch.object(deps, 'run') as command:
            self.assertTrue(deps.ensure_dependencies())
            command.assert_not_called()

    def test_dependency_failure_blocks_application_installation(self):
        with patch.object(install, 'ensure_dependencies', return_value=False), \
                patch.object(install, 'check_compatibility') as check, \
                patch.object(install, 'install_files') as mutate:
            self.assertEqual(install.install(), 1)
            check.assert_not_called()
            mutate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
