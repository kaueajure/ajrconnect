"""Local discovery, power command boundaries and isolated GTK actions; no live VM."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core
import vm_control as vm


class MachineTests(unittest.TestCase):
    def test_socket_symlink_is_detected_and_not_listed_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / 'engine.sock'
            linked = home / '.docker/desktop/docker.sock'
            linked.parent.mkdir(parents=True)
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(target))
                linked.symlink_to(target)
                self.assertTrue(vm.is_socket(linked))
                with patch.object(vm.Path, 'home', return_value=home), \
                        patch.dict(os.environ, {'DOCKER_HOST': 'unix://' + str(target)}, clear=True):
                    candidates = vm.docker_socket_candidates('docker-user')
                self.assertEqual(candidates, [target])

    def test_selected_local_context_discovers_stopped_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / 'client-config'
            context = 'local-windows'
            digest = hashlib.sha256(context.encode()).hexdigest()
            metadata = config / 'contexts/meta' / digest / 'meta.json'
            metadata.parent.mkdir(parents=True)
            (config / 'config.json').write_text(json.dumps({'currentContext': context}))
            target = home / 'custom-engine.sock'
            metadata.write_text(json.dumps({'Endpoints': {'docker': {'Host': 'unix://' + str(target)}}}))
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(target))
                with patch.object(vm.Path, 'home', return_value=home), \
                        patch.dict(os.environ, {'DOCKER_CONFIG': str(config)}, clear=True), \
                        patch.object(vm, 'find_tool', side_effect=lambda tool: '/usr/bin/docker' if tool == 'docker' else None), \
                        patch.object(vm.subprocess, 'run', return_value=subprocess.CompletedProcess(
                            [], 0, '{"id":"windows-id","name":"Windows","state":"exited"}', '')) as run:
                    machines, notices, restricted = vm.discover()
                    local = [m for m in machines if m.backend == 'docker-user']
                    self.assertEqual([(m.name, m.state) for m in local], [('Windows', 'exited')])
                    vm.power(local[0], 'start')
                    args = run.call_args.args[0]
                    self.assertEqual(args[1:3], ['--host', 'unix://' + str(target)])
                    self.assertEqual(args[-2:], ['start', 'windows-id'])

    def test_rootless_runtime_directory_is_respected(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {'XDG_RUNTIME_DIR': directory}, clear=True):
            target = Path(directory) / 'docker.sock'
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(target))
                self.assertEqual(vm.resolve_docker_socket('docker-user'), (target, 'ok'))

    def test_remote_hosts_and_invalid_context_metadata_are_ignored(self):
        for host in ('ssh://remote', 'tcp://remote:2375', 'unix://remote/docker.sock', 'unix:relative',
                     'unix:///run/docker.sock?remote=1', 'unix:///run/docker%00.sock'):
            with self.subTest(host=host), patch.dict(os.environ, {'DOCKER_HOST': host}, clear=True):
                self.assertIsNone(vm.configured_docker_socket())
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {'DOCKER_CONFIG': directory}, clear=True):
            config = Path(directory) / 'config.json'
            for content in ('invalid json', '[]', '{"currentContext": {"invalid": true}}'):
                config.write_text(content)
                self.assertIsNone(vm.configured_docker_socket())

    def test_discovery_includes_stopped_containers_without_exposing_configuration(self):
        payload = '\n'.join(json.dumps(dict(id=identifier, name=name, state=state))
            for identifier, name, state in [('aaa', 'Windows SQL', 'running'), ('bbb', 'Lab', 'exited')])
        with patch.object(vm, 'run', return_value=payload) as run:
            machines = vm.discover_backend('docker')
        self.assertEqual([(machine.name, machine.state) for machine in machines],
                         [('Windows SQL', 'running'), ('Lab', 'exited')])
        command = run.call_args.args[1]
        self.assertIn('--all', command)
        self.assertIn('--no-trunc', command)
        self.assertNotIn('.Command', command[-1])
        self.assertNotIn('.Env', command[-1])

    def test_podman_names_and_libvirt_and_virtualbox_identity(self):
        with patch.object(vm, 'run', return_value='{"id":"abc","name":["Windows"],"state":"exited"}'):
            self.assertEqual(vm.discover_backend('podman')[0].name, 'Windows')
        identifier = '12345678-1234-1234-1234-123456789abc'
        with patch.object(vm, 'run', side_effect=[identifier+'\n', 'Windows\n', 'shut off\n']):
            machine = vm.discover_backend('libvirt')[0]
            self.assertEqual((machine.identifier, machine.state), (identifier, 'shut off'))
        entry = f'"Windows Lab" {{{identifier}}}\n'
        with patch.object(vm, 'run', side_effect=[entry, entry]):
            self.assertEqual(vm.discover_backend('virtualbox')[0].state, 'running')

    def test_discovery_is_read_only_and_denied_access_is_not_empty_success(self):
        with patch.object(vm, 'find_tool', side_effect=lambda tool: '/usr/bin/docker' if tool == 'docker' else None), \
                patch.object(vm, 'docker_host_args',
                             return_value=(('--host', 'unix:///var/run/docker.sock'), 'ok', Path('/var/run/docker.sock'))), \
                patch.object(vm, 'run', side_effect=vm.VMError('permission denied', permission=True)) as run:
            machines, notices, restricted = vm.discover()
        self.assertFalse(machines)
        self.assertEqual(restricted, ['docker'])
        self.assertTrue(any('autorização do sistema' in notice for notice in notices))
        self.assertFalse(run.call_args.kwargs['elevated'])

    def test_discovery_explains_missing_daemon_and_socket_acl(self):
        with patch.object(vm, 'find_tool', side_effect=lambda tool: '/usr/bin/docker' if tool == 'docker' else None), \
                patch.object(vm, 'docker_host_args',
                             return_value=(('--host', 'unix:///var/run/docker.sock'), 'missing', Path('/var/run/docker.sock'))), \
                patch.object(vm, 'run', side_effect=vm.VMError(
                    'Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?')):
            machines, notices, restricted = vm.discover()
        self.assertFalse(machines)
        self.assertFalse(restricted)
        self.assertTrue(any('serviço local' in notice or 'daemon' in notice.casefold() for notice in notices))
        with patch.object(vm, 'find_tool', side_effect=lambda tool: '/usr/bin/docker' if tool == 'docker' else None), \
                patch.object(vm, 'docker_host_args',
                             return_value=(('--host', 'unix:///var/run/docker.sock'), 'denied', Path('/var/run/docker.sock'))):
            machines, notices, restricted = vm.discover()
        self.assertEqual(restricted, ['docker'])
        self.assertTrue(any('autorização do sistema' in notice for notice in notices))

    def test_ensure_docker_group_skips_when_already_configured(self):
        with patch.object(vm, 'docker_group_configured', return_value=True):
            self.assertFalse(vm.ensure_docker_group())
        with patch.object(vm, 'docker_group_configured', return_value=False), \
                patch.object(vm, 'current_username', return_value='alice'), \
                patch.object(vm, 'find_tool', side_effect=lambda name: '/usr/bin/' + name), \
                patch.object(vm.subprocess, 'run',
                             return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            self.assertTrue(vm.ensure_docker_group())
        self.assertEqual(run.call_args.args[0],
                         ['/usr/bin/pkexec', '/usr/bin/usermod', '-aG', 'docker', 'alice'])

    def test_docker_format_fallback_and_desktop_socket_order(self):
        tabular = 'abc123\tWindows\tUp 2 minutes\n'
        with patch.object(vm, 'run', side_effect=[
                vm.VMError('template parsing error'), tabular]):
            machines = vm.discover_docker('docker')
        self.assertEqual([(m.name, m.state) for m in machines], [('Windows', 'running')])
        with patch.object(vm, 'is_socket', side_effect=lambda path: str(path).endswith('desktop/docker.sock')), \
                patch.object(vm.os, 'access', return_value=True), \
                patch.object(vm.os, 'getuid', return_value=1000):
            path, status = vm.resolve_docker_socket('docker')
        self.assertEqual(status, 'ok')
        self.assertTrue(str(path).endswith('.docker/desktop/docker.sock'))

    def test_power_commands_are_scoped_and_never_force_kill_or_destroy(self):
        for backend in vm.BACKENDS:
            for action in ('start', 'stop'):
                with self.subTest(backend=backend, action=action), patch.object(vm, 'run') as run:
                    vm.power(vm.Machine(backend, 'target-id', 'Windows'), action)
                    arguments = run.call_args.args[1]
                    self.assertIn('target-id', arguments)
                    self.assertNotIn('kill', arguments)
                    self.assertNotIn('destroy', arguments)
                    self.assertNotIn('poweroff', arguments)
                    if action == 'stop' and backend in ('docker', 'docker-user', 'podman'):
                        self.assertEqual(arguments, ['stop', '--timeout', '120', 'target-id'])
                    if action == 'stop' and backend.startswith('libvirt'):
                        self.assertEqual(arguments[0], 'shutdown')
                    if action == 'stop' and backend == 'virtualbox':
                        self.assertEqual(arguments[-1], 'acpipowerbutton')

    def test_local_endpoint_and_no_shell_or_automatic_escalation(self):
        result = subprocess.CompletedProcess([], 0, 'ok', '')
        with patch.object(vm, 'find_tool', side_effect=lambda name: '/usr/bin/'+name), \
                patch.object(vm, 'docker_host_args',
                             return_value=(('--host', 'unix:///var/run/docker.sock'), 'ok', Path('/var/run/docker.sock'))), \
                patch.object(vm.subprocess, 'run', return_value=result) as run, \
                patch.dict(os.environ, DOCKER_HOST='ssh://remote', DOCKER_CONTEXT='remote'):
            vm.power(vm.Machine('docker', 'abc', 'Windows'), 'start')
            args, kwargs = run.call_args
            self.assertEqual(args[0], ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'start', 'abc'])
            self.assertNotIn('shell', kwargs)
            self.assertNotIn('DOCKER_HOST', kwargs['env'])
            self.assertNotIn('DOCKER_CONTEXT', kwargs['env'])
            self.assertEqual(vm.command('docker', ['start', 'abc'], elevated=True)[0], '/usr/bin/pkexec')
        with self.assertRaises(vm.VMError):
            vm.power(vm.Machine('docker', '--all', 'Windows'), 'stop')
        with self.assertRaises(vm.VMError):
            vm.power(vm.Machine('docker', 'abc', 'Windows'), 'delete')

    def test_permission_cancel_timeout_and_invalid_output(self):
        with patch.object(vm, 'find_tool', return_value='/usr/bin/docker'), \
                patch.object(vm, 'docker_host_args',
                             return_value=(('--host', 'unix:///var/run/docker.sock'), 'ok', Path('/var/run/docker.sock'))), \
                patch.object(vm.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'permission denied')):
            with self.assertRaises(vm.VMError) as denied:
                vm.run('docker', ['ps'])
            self.assertTrue(denied.exception.permission)
        with patch.object(vm, 'find_tool', return_value='/usr/bin/docker'), \
                patch.object(vm, 'docker_host_args',
                             return_value=(('--host', 'unix:///var/run/docker.sock'), 'ok', Path('/var/run/docker.sock'))), \
                patch.object(vm.subprocess, 'run', side_effect=subprocess.TimeoutExpired('docker', 15)):
            with self.assertRaisesRegex(vm.VMError, 'tempo'):
                vm.run('docker', ['ps'])
        with patch.object(vm, 'find_tool', return_value='/usr/bin/docker'), \
                patch.object(vm, 'docker_host_args',
                             return_value=(('--host', 'unix:///var/run/docker.sock'), 'ok', Path('/var/run/docker.sock'))), \
                patch.object(vm.subprocess, 'run', return_value=subprocess.CompletedProcess([], 126, '', 'cancelled')):
            with self.assertRaisesRegex(vm.VMError, 'cancelada'):
                vm.run('docker', ['ps'], elevated=True)

    def test_machine_bindings_follow_profiles_and_restart(self):
        cfg = copy.deepcopy(core.DEFAULT)
        cfg.update(vm_backend='docker', vm_id='first-id', vm_name='Windows SQL')
        first = core.store_profile(cfg, 'Primeira')['id']
        cfg.update(active_profile='', vm_backend='virtualbox', vm_id='second-id', vm_name='Windows Lab')
        second = core.store_profile(cfg, 'Segunda')['id']
        core.select_profile(cfg, first)
        with tempfile.TemporaryDirectory() as folder, patch.object(core, 'CFG_FILE', Path(folder)/'config.json'):
            core.save_cfg(cfg)
            restored = core.load_cfg()
        self.assertEqual(restored['vm_id'], 'first-id')
        core.select_profile(restored, second)
        self.assertEqual(restored['vm_id'], 'second-id')
        for backend in ([], {}, None, 'unknown'):
            self.assertEqual(core.normalize_settings(dict(vm_backend=backend, vm_id='x', vm_name='Windows'))['vm_id'], '')


GUI_SCRIPT = r'''
import sys, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import ajr_app as gui
import vm_control as vm
from gi.repository import Gio, GLib, Gtk
def drain(until=None):
    end=time.monotonic()+3
    while time.monotonic()<end:
        while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
        if until is None or until(): return
        time.sleep(.01)
    raise AssertionError('UI worker timed out')
app=gui.App(); app.set_flags(Gio.ApplicationFlags.NON_UNIQUE); app.register(None)
machines=[vm.Machine('docker','first-id','Windows SQL','exited'),vm.Machine('virtualbox','second-id','Windows Lab','running')]
with patch.object(gui,'secret',return_value=''), patch.object(gui,'detect_monitors',return_value=[]), \
        patch.object(gui.socket,'create_connection',side_effect=OSError('isolated')), \
        patch.object(vm,'discover',return_value=(machines,[],[])), patch.object(vm,'power') as power:
    win=gui.MainWindow(app); win.present(); win.open_machines()
    window=win._machine_window
    drain(lambda: not window.busy)
    assert window.selection.get_selected()==Gtk.INVALID_LIST_POSITION
    assert not window.start.get_sensitive() and not window.stop.get_sensitive()
    window.selection.set_selected(0); window.bind()
    assert win.cfg['vm_id']=='first-id' and window.start.get_sensitive()
    window.request_power('start'); drain(lambda: not window.busy)
    power.assert_called_once_with(machines[0],'start',elevated=False)
    power.reset_mock()
    window.selection.set_selected(1); window.bind()
    assert window.stop.get_sensitive() and not window.start.get_sensitive()
    window.request_power('stop'); drain()
    dialog=next(w for w in Gtk.Window.get_toplevels() if isinstance(w,gui.Adw.MessageDialog) and w.get_visible() and w.get_heading()=='Desligar esta máquina?')
    dialog.response('cancel'); drain(); power.assert_not_called()
    window.request_power('stop'); drain()
    dialog=next(w for w in Gtk.Window.get_toplevels() if isinstance(w,gui.Adw.MessageDialog) and w.get_visible() and w.get_heading()=='Desligar esta máquina?')
    with patch.object(win,'connection_busy',return_value=True), patch.object(win,'cancel_connection') as cancel:
        dialog.response('stop'); drain(lambda: not window.busy)
        cancel.assert_called_once()
    power.assert_called_once_with(machines[1],'stop',elevated=False)
    window.remove_binding(); assert not win.cfg['vm_id'] and not window.stop.get_sensitive()
    window.close(); drain(); assert win._machine_window is None
    win.close(); drain()
print('PASS machine GTK: discovery, explicit binding, start, stop confirmation/cancel, RDP cancellation and unlink')
'''


class MachineUITests(unittest.TestCase):
    def test_discovery_binding_and_power_actions(self):
        import test_preferences
        test_preferences.GtkPreferencesTests.run_gui_script(self, GUI_SCRIPT)
