"""Hypervisor RAM limit helpers and isolated GTK apply/status actions."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core
import memory_monitor as mem
import vm_control as vm


class MemoryTests(unittest.TestCase):
    def test_parse_size_and_describe(self):
        self.assertEqual(vm.parse_size('1.5GiB'), int(1.5 * vm.GIB))
        self.assertEqual(vm.parse_size('512MiB'), 512 * vm.MIB)
        status = vm.MemoryStatus(3 * vm.GIB, 4 * vm.GIB, True)
        self.assertIn('3.00 GiB', mem.describe(status))
        self.assertIn('4', mem.describe(status))

    def test_bound_machine_requires_valid_link(self):
        cfg = copy.deepcopy(core.DEFAULT)
        self.assertIsNone(vm.bound_machine(cfg))
        cfg.update(vm_backend='docker', vm_id='abc', vm_name='Windows', vm_host='')
        self.assertEqual(vm.bound_machine(cfg).identifier, 'abc')
        cfg['vm_host'] = 'ssh://lab'
        self.assertEqual(vm.bound_machine(cfg).endpoint, 'ssh://lab')
        cfg['vm_host'] = 'not-a-url'
        self.assertIsNone(vm.bound_machine(cfg))

    def test_docker_set_limit_and_status(self):
        machine = vm.Machine('docker', 'cid', 'Windows')
        with patch.object(vm, 'run', side_effect=['', '4294967296', 'true', '1.25GiB / 4GiB']) as run:
            vm.set_memory_limit(machine, 4)
            status = vm.memory_status(machine)
        self.assertEqual(run.call_args_list[0].args[1][:3], ['update', '--memory', '4096m'])
        self.assertEqual(run.call_args_list[0].args[1][3:5], ['--memory-swap', '4096m'])
        self.assertEqual(status, vm.MemoryStatus(int(1.25 * vm.GIB), 4294967296, True))

    def test_libvirt_and_virtualbox_limits(self):
        libvirt = vm.Machine('libvirt', 'uuid', 'Windows')
        with patch.object(vm, 'run') as run:
            vm.set_memory_limit(libvirt, 2)
            args = [call.args[1] for call in run.call_args_list]
        self.assertTrue(any(item[0] == 'setmaxmem' and '2097152' in item for item in args))
        self.assertTrue(any(item[0] == 'setmem' and '--config' in item for item in args))
        with patch.object(vm, 'run', return_value='Max memory: 2097152 KiB\nUsed memory: 1048576 KiB\nState: running\n'):
            status = vm.memory_status(libvirt)
        self.assertEqual(status.used_bytes, vm.GIB)
        self.assertEqual(status.limit_bytes, 2 * vm.GIB)
        vbox = vm.Machine('virtualbox', 'uuid', 'Windows')
        with patch.object(vm, 'run', side_effect=[
                'memory=2048\nVMState="poweroff"\n',
                '',
        ]) as run:
            vm.set_memory_limit(vbox, 3)
        self.assertEqual(run.call_args.args[1], ['modifyvm', 'uuid', '--memory', '3072'])
        with patch.object(vm, 'run', return_value='memory=2048\nVMState="running"\n'):
            with self.assertRaisesRegex(vm.VMError, 'Desligue'):
                vm.set_memory_limit(vbox, 3)

    def test_power_start_applies_memory_before_boot(self):
        machine = vm.Machine('docker', 'cid', 'Windows')
        with patch.object(vm, 'set_memory_limit') as limit, patch.object(vm, 'run') as run:
            vm.power(machine, 'start', memory_gib=2.5)
        limit.assert_called_once_with(machine, 2.5, elevated=False)
        self.assertEqual(run.call_args.args[1], ['start', 'cid'])
        with patch.object(vm, 'set_memory_limit') as limit, patch.object(vm, 'run'):
            vm.power(machine, 'stop', memory_gib=2.5)
        limit.assert_not_called()


GUI_SCRIPT = r'''
import copy, sys, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import ajr_app as gui
import vm_control as vm
from gi.repository import Gio, GLib
from core import RESOLUTIONS
def drain():
    until = time.monotonic() + .2
    while time.monotonic() < until:
        while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
        time.sleep(.005)
app = gui.App(); app.set_flags(Gio.ApplicationFlags.NON_UNIQUE); app.register(None)
with patch.object(gui, 'secret', return_value=''), patch.object(gui, 'detect_monitors', return_value=[]), \
        patch.object(gui.socket, 'create_connection', side_effect=OSError('isolated')):
    win = gui.MainWindow(app)
    win.present()
    win.resolution.set_selected(1)
    win.ram_alert.set_active(True)
    win.ram_limit.set_value(2.5)
    win.persist()
    assert win.cfg['resolution'] == '4k' and win.cfg['ram_limit_gib'] == 2.5
    win.cfg.update(resolution='360p', ram_alert=False, ram_limit_gib=3)
    win.apply_profile()
    assert RESOLUTIONS[win.resolution.get_selected()][0] == '360p'
    assert not win.ram_limit.get_sensitive()
    win.ram_alert.set_active(True)
    win.cfg.update(vm_backend='docker', vm_id='cid', vm_name='Windows', vm_host='')
    status = vm.MemoryStatus(1 * vm.GIB, 2 * vm.GIB, True)
    with patch.object(vm, 'set_memory_limit') as limit, patch.object(vm, 'memory_status', return_value=status):
        win.apply_vm_memory_limit(); drain()
        limit.assert_called_once()
        assert '1.00 GiB' in win.ram_status.get_subtitle()
    win.open_memory_monitor(); drain()
    assert win._ram_guide
    win._ram_guide.response('close'); drain()
    win.close(); drain()
print('PASS RAM GTK: hypervisor limit apply, status and dialog')
'''


class MemoryUITests(unittest.TestCase):
    def test_warning_actions(self):
        import test_preferences
        test_preferences.GtkPreferencesTests.run_gui_script(self, GUI_SCRIPT)
