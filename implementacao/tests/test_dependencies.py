"""Exercise dependency plans without sudo, network or system package changes."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dependencies as deps
import install


class DependencyTests(unittest.TestCase):
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
        self.assertNotIn('gnome-shell', transaction)
        self.assertNotIn('--allow-downgrades', transaction)
        simulation = next(command for command in calls if '--simulate' in command)
        self.assertLess(calls.index(simulation), calls.index(transaction))

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
        for stage in ('update', '--simulate', 'install'):
            with self.subTest(stage=stage):
                result, calls = self.plan(missing=('libsecret-tools',),
                                          failure=lambda command: stage in command)
                self.assertFalse(result)
                if stage != 'install':
                    self.assertFalse(any(command[:2] == ['sudo', 'apt-get'] and 'install' in command
                                         for command in calls))

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
