"""Release selection, verified downloads, safe extraction and update rollback."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import updates
import install
import test_preferences as gui_harness


def release_entry(tag, *, prerelease=True):
    return dict(tag_name=tag, prerelease=prerelease, draft=False, assets=[
        dict(name=updates.ASSET, state='uploaded', size=100),
        dict(name='SHA256SUMS', state='uploaded')])


def archive_bytes(files):
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode='w:gz') as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return content.getvalue()


class ReleaseTests(unittest.TestCase):
    def test_semantic_versions_and_no_downgrade(self):
        self.assertLess(updates.version_key('6.0.0-beta.9'), updates.version_key('6.0.0-beta.10'))
        self.assertLess(updates.version_key('6.0.0-beta.99'), updates.version_key('6.0.0'))
        self.assertEqual(updates.version_key('v6.0.0+build'), updates.version_key('6.0.0'))
        self.assertIsNone(updates.select_release([release_entry('v6.0.0-beta.6')], '6.0.0-beta.7'))

    def test_beta_channel_drafts_missing_assets_and_invalid_tags(self):
        releases = [release_entry('v6.1.0-beta.1'), release_entry('v6.0.0', prerelease=False)]
        self.assertEqual(updates.select_release(releases, '6.0.0-beta.6').tag, 'v6.1.0-beta.1')
        self.assertEqual(updates.select_release(releases, '6.0.0-beta.6', False).tag, 'v6.0.0')
        broken = release_entry('v8.0.0')
        broken['assets'].pop()
        draft = release_entry('v9.0.0')
        draft['draft'] = True
        self.assertIsNone(updates.select_release([broken, draft, release_entry('../../x')], '6.0.0'))

    def test_discovery_uses_public_release_metadata(self):
        with patch.object(updates, 'read_small', return_value=json.dumps([release_entry('v6.0.0-beta.8')]).encode()):
            self.assertEqual(updates.check_updates(current='6.0.0-beta.7').tag, 'v6.0.0-beta.8')


class DownloadTests(unittest.TestCase):
    def fixture(self, script=b"import sys\nassert sys.argv[1:] == ['--update']\n"):
        data = archive_bytes({'ajr-connect/version.py': b"APP_VERSION = '6.0.0-beta.8'\n",
                              'ajr-connect/install.py': script})
        digest = hashlib.sha256(data).hexdigest()
        release = updates.Release('v6.0.0-beta.8', len(data), 'sha256:' + digest)
        checksums = (digest + '  ' + updates.ASSET + '\n').encode()
        def response(url):
            return io.BytesIO(checksums if url.endswith('SHA256SUMS') else data)
        return release, response

    def test_download_install_and_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'installed'
            script = ("import sys\nfrom pathlib import Path\nassert sys.argv[1:] == ['--update']\n"
                      f"Path({str(marker)!r}).write_text('installed')\n").encode()
            release, response = self.fixture(script)
            progress = []
            with patch.object(updates, 'open_url', side_effect=response), \
                    patch.object(updates, 'installed_application', return_value=True), \
                    patch.object(updates, 'INSTALL_LOG', root / 'update.log'):
                self.assertEqual(updates.apply_update(release, threading.Event(),
                    lambda stage, fraction: progress.append((stage, fraction))), '6.0.0-beta.8')
            self.assertTrue(marker.exists())
            self.assertEqual(progress[-1], ('install', 1))

    def test_corrupt_download_does_not_run_installer(self):
        release, response = self.fixture()
        def corrupt(url):
            return response(url) if url.endswith('SHA256SUMS') else io.BytesIO(b'x' * release.size)
        with patch.object(updates, 'open_url', side_effect=corrupt), \
                patch.object(updates, 'installed_application', return_value=True), \
                patch.object(updates.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'integridade'):
                updates.apply_update(release, threading.Event(), lambda *_: None)
            run.assert_not_called()

    def test_cancellation_before_download_and_during_stream(self):
        release, response = self.fixture()
        cancel = threading.Event()
        cancel.set()
        with tempfile.TemporaryDirectory() as directory, patch.object(updates, 'open_url') as open_url:
            with self.assertRaises(updates.UpdateCancelled):
                updates.download_release(release, Path(directory) / 'package', cancel, lambda *_: None)
            open_url.assert_not_called()
        cancel.clear()
        with tempfile.TemporaryDirectory() as directory, patch.object(updates, 'open_url', side_effect=response):
            with self.assertRaises(updates.UpdateCancelled):
                updates.download_release(release, Path(directory) / 'package', cancel,
                                         lambda *_: cancel.set())

    def test_conflicting_digest_is_rejected(self):
        release, response = self.fixture()
        release = updates.Release(release.tag, release.size, 'sha256:' + '0' * 64)
        with tempfile.TemporaryDirectory() as directory, patch.object(updates, 'open_url', side_effect=response):
            with self.assertRaisesRegex(ValueError, 'hashes'):
                updates.download_release(release, Path(directory) / 'package', None, lambda *_: None)

    def test_archive_cannot_write_outside_staging_or_create_links(self):
        for name, kind in [('ajr-connect/../../outside', tarfile.REGTYPE),
                           ('/outside', tarfile.REGTYPE), ('ajr-connect/link', tarfile.SYMTYPE),
                           ('ajr-connect/device', tarfile.CHRTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive_path = root / 'package.tar.gz'
                with tarfile.open(archive_path, 'w:gz') as archive:
                    member = tarfile.TarInfo(name)
                    member.type, member.linkname = kind, '/tmp/outside'
                    archive.addfile(member)
                with self.assertRaises(ValueError):
                    updates.extract_package(archive_path, root / 'stage')
                self.assertFalse((root / 'outside').exists())

    def test_installer_failure_and_timeout_require_recovery(self):
        release, response = self.fixture()
        for result in (subprocess.CompletedProcess([], 1), subprocess.TimeoutExpired('installer', 180)):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as directory, \
                    patch.object(updates, 'open_url', side_effect=response), \
                    patch.object(updates, 'installed_application', return_value=True), \
                    patch.object(updates, 'INSTALL_LOG', Path(directory) / 'update.log'), \
                    patch.object(updates.subprocess, 'run', side_effect=[result, subprocess.CompletedProcess([], 0)]) as run:
                with self.assertRaises(RuntimeError):
                    updates.apply_update(release, threading.Event(), lambda *_: None)
                if isinstance(result, subprocess.TimeoutExpired):
                    self.assertEqual(run.call_args.args[0][-1], '--recover-update')


class UpdateInstallerTests(unittest.TestCase):
    def test_update_preserves_config_and_restores_partial_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                data = home / '.local/share/ajr-connect'
                app = data / 'app'
                app.mkdir(parents=True)
                (app / 'ajr_app.py').write_text('previous application')
                cfg = home / '.config/ajr-connect/config.json'
                cfg.parent.mkdir(parents=True)
                cfg.write_text('{"server":"private.example","profiles":[]}')
                original = cfg.read_bytes()
                metadata = data / 'last-install.json'
                metadata.write_text('{"release":"old"}')
                parameters = dict(HOME=home, DATA=data, APP=app,
                    EXT=home / '.local/share/gnome-shell/extensions/ajr-connect@ajure.local',
                    BIN=home / '.local/bin/ajr-connect', CFG=cfg,
                    DESKTOP=home / '.local/share/applications/ajr-connect.desktop',
                    BACKUP=data / 'backups/test', UPDATE_JOURNAL=data / 'update-in-progress.json', UPDATING=False)
                original_copy = install.shutil.copy2
                def copy(source, destination, *args, **kwargs):
                    if fail and Path(source) == install.BASE / 'ui.py' and Path(destination) == app / 'ui.py':
                        raise OSError('simulated write failure')
                    return original_copy(source, destination, *args, **kwargs)
                with patch.multiple(install, **parameters), \
                        patch.object(install, 'check_package', return_value=True), \
                        patch.object(install, 'check_compatibility', return_value=True), \
                        patch.object(install, 'lookup_settings', return_value=None), \
                        patch.object(install, 'ensure_dependencies') as deps, \
                        patch.object(install.shutil, 'copy2', side_effect=copy):
                    self.assertEqual(install.install(updating=True), int(fail))
                    deps.assert_not_called()
                    self.assertFalse(install.UPDATE_JOURNAL.exists())
                self.assertEqual(cfg.read_bytes(), original)
                if fail:
                    self.assertEqual((app / 'ajr_app.py').read_text(), 'previous application')
                    self.assertEqual(json.loads(metadata.read_text())['release'], 'old')
                else:
                    self.assertTrue((app / 'updates.py').exists())


GUI_SCRIPT = r'''
import sys, threading, time
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, sys.argv[1])
import ajr_app as gui
import updates
from gi.repository import Gio, GLib
def drain(duration=.15):
    until = time.monotonic() + duration
    while time.monotonic() < until:
        while GLib.MainContext.default().pending() and time.monotonic() < until:
            GLib.MainContext.default().iteration(False)
        time.sleep(.005)
app = gui.App()
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
with patch.object(gui, 'secret', return_value=''), patch.object(gui, 'detect_monitors', return_value=[]), \
        patch.object(gui.socket, 'create_connection', side_effect=OSError('offline')):
    win = gui.MainWindow(app)
    win.present()
    # Network verification errors are visible and can be retried.
    with patch.object(updates, 'check_updates', side_effect=OSError('offline')):
        win.open_updates()
        drain()
        dialog = win._update_window
        assert 'Não foi possível verificar' in dialog.status.get_text()
        assert dialog.action.get_sensitive()
        dialog.close()
    release = updates.Release('v6.0.0-beta.8', 100)
    with patch.object(updates, 'check_updates', return_value=release), \
            patch.object(updates, 'installed_application', return_value=True):
        win.open_updates()
        drain()
        dialog = win._update_window
        assert dialog.release == release and dialog.notes.get_visible()
        assert dialog.action.get_label() == 'Baixar e atualizar'
        # Session startup also blocks an update, even before the RDP process exists.
        win._launching = True
        dialog.install()
        assert not win._updating and 'Desconecte' in dialog.status.get_text()
        win._launching = False
        def cancelled(release, cancel, progress):
            progress('download', .5)
            cancel.wait(2)
            raise updates.UpdateCancelled()
        with patch.object(updates, 'apply_update', side_effect=cancelled):
            dialog.install()
            drain()
            assert win._updating and not win.form.get_sensitive()
            assert abs(dialog.progress.get_fraction() - .5) < .01
            dialog.cancel_download()
            drain()
            assert not win._updating and win.form.get_sensitive()
            assert 'cancelado' in dialog.status.get_text()
        finish = threading.Event()
        def installed(release, cancel, progress):
            progress('install', 1)
            finish.wait(2)
            return '6.0.0-beta.8'
        with patch.object(updates, 'apply_update', side_effect=installed):
            dialog.install()
            drain()
            assert dialog.phase == 'install' and not dialog.cancel_button.get_sensitive()
            assert dialog.close_requested() is True
            finish.set()
            drain()
            assert win._update_ready and not win._updating and not win.form.get_sensitive()
            assert dialog.action.get_label() == 'Reiniciar aplicativo'
            count = win._connection_generation
            win.do_connect()
            assert count == win._connection_generation
        with patch.object(gui.subprocess, 'Popen') as launch, \
                patch.object(win, 'get_application', return_value=Mock()) as application:
            dialog.activate()
            assert '--restart' in launch.call_args.args[0]
            application.return_value.quit.assert_called_once()
        win._closing = False
        dialog.close()
        win._update_ready = False
        win.finish_connection()
    win.close()
    drain()
print('PASS GTK updates: discovery/error, busy session, cancel/progress, installation and restart')
'''


class GtkUpdateTests(unittest.TestCase):
    def test_updates_on_private_display(self):
        gui_harness.GtkPreferencesTests.run_gui_script(self, GUI_SCRIPT)


if __name__ == '__main__':
    unittest.main()
