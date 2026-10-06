#!/usr/bin/env python3
"""Real permission dialog and keyboard portal in a throwaway GNOME desktop."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

BASE = Path(__file__).resolve().parents[1]
DRIVER = r'''
import json, os, subprocess, sys, time
from pathlib import Path
from gi.repository import Gio, GLib
sys.path.insert(0, sys.argv[1])
from integration import install_extension, EXTENSION_ID
from keyboard_portal import KeyboardPortal
source = Path.home() / 'source'
code = (source / 'integration.js').read_text()
code = "import Shell from 'gi://Shell';\n" + code
code = code.replace('<interface name="com.ajure.AJRConnect.Keyboard">',
    '<interface name="com.ajure.AJRConnect.Keyboard">'
    '<method name="TestState"><arg type="u" direction="out"/></method>'
    '<method name="TestShot"><arg type="s" direction="out"/></method>'
    '<method name="TestFocus"><arg type="u" direction="in"/></method>')
code = code.replace('    Ping() {', """
    TestState() { return global.workspace_manager.get_active_workspace_index(); }
    TestShotAsync(_args, invocation) {
        const path = GLib.build_filenamev([GLib.get_home_dir(), 'permission.png']);
        const stream = Gio.File.new_for_path(path).replace(null, false, Gio.FileCreateFlags.NONE, null);
        new Shell.Screenshot().screenshot(false, stream).then(() => {
            stream.close(null);
            invocation.return_value(new GLib.Variant('(s)', [path]));
        }).catch(error => invocation.return_dbus_error('com.ajure.TestError', error.message));
    }
    TestFocus(pid) {
        Main.overview.hide();
        global.get_window_actors().map(actor => actor.meta_window)
            .find(win => pid ? win.get_pid() === pid : win.get_title() === 'Remote Desktop')?.activate(global.get_current_time());
    }
    Ping() {
""", 1)
(source / 'integration.js').write_text(code)
target = Path.home() / '.local/share/gnome-shell/extensions' / EXTENSION_ID
install_extension(source, target)
Gio.Settings.new('org.gnome.shell').set_strv('enabled-extensions', [EXTENSION_ID])
Gio.Settings.sync()
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
def call(method, params=None, result='()'):
    return bus.call_sync('org.gnome.Shell', '/com/ajure/AJRConnect',
        'com.ajure.AJRConnect.Keyboard', method, params, GLib.VariantType.new(result),
        Gio.DBusCallFlags.NONE, 1000, None).unpack()
def drain(duration=.2):
    until = time.monotonic() + duration
    while time.monotonic() < until:
        while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
        time.sleep(.005)
processes = []
with (Path.home() / 'session.log').open('w') as log:
    processes.append(subprocess.Popen(['pipewire'], stdout=log, stderr=subprocess.STDOUT))
    shell = subprocess.Popen(['gnome-shell', '--headless', '--wayland', '--virtual-monitor', '1024x768', '--sm-disable'], stdout=log, stderr=subprocess.STDOUT)
    processes.append(shell)
    pid = shell.pid
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if call('Ping', result='(b)')[0]: break
            except GLib.Error: pass
            drain(.1)
        else: raise RuntimeError('Private compositor did not start')
        os.environ['WAYLAND_DISPLAY'] = next(path.name for path in Path(os.environ['XDG_RUNTIME_DIR']).glob('wayland-*') if path.is_socket())
        os.environ['GDK_BACKEND'] = 'wayland'
        # All services use the private bus, display, HOME and permission store.
        bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
            'org.freedesktop.DBus', 'UpdateActivationEnvironment',
            GLib.Variant('(a{ss})', ({key: os.environ[key] for key in
                ('WAYLAND_DISPLAY', 'GDK_BACKEND', 'XDG_CURRENT_DESKTOP')},)),
            None, Gio.DBusCallFlags.NONE, 1000, None)
        states = []
        portal = KeyboardPortal(lambda *args: states.append(args))
        portal.start()
        deadline = time.monotonic() + 10
        while not portal.session and portal.pending and time.monotonic() < deadline: drain(.1)
        assert portal.session, states
        drain(1.5)
        call('TestFocus', GLib.Variant('(u)', (0,)))
        drain(.4)
        # AT-SPI acts only on the private test permission dialog. Production
        # code never approves a permission on behalf of the user.
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
        def nodes(node):
            yield node
            for i in range(node.get_child_count()):
                child = node.get_child_at_index(i)
                if child:
                    yield from nodes(child)
        desktop = Atspi.get_desktop(0)
        deadline = time.monotonic() + 10
        interaction = None
        while time.monotonic() < deadline and portal.pending:
            try:
                applications = [desktop.get_child_at_index(i) for i in range(desktop.get_child_count())]
                portal_app = next(app for app in applications if app.get_name() == 'xdg-desktop-portal-gnome')
                interaction = next(node for node in nodes(portal_app) if 'Allow Remote Interaction' in node.get_name() and node.get_role() == Atspi.Role.CHECK_BOX)
                break
            except (StopIteration, GLib.Error):
                drain(.1)
        assert interaction, ('Private consent dialog did not become accessible', states)
        interface = interaction.get_action_iface()
        assert interface and interface.do_action(0), 'Test interaction toggle failed'
        drain(.4)
        call('TestShot', result='(s)')
        share = next(node for node in nodes(portal_app) if node.get_name() == 'Share' and node.get_role() == Atspi.Role.PUSH_BUTTON)
        assert share.get_action_iface().do_action(0), 'Test Share button failed'
        deadline = time.monotonic() + 8
        while portal.pending and time.monotonic() < deadline: drain(.1)
        assert portal.ready, states
        assert portal.token_path.exists(), 'GNOME did not return a persistent token'
        Gio.Settings.new('org.gnome.mutter').set_boolean('dynamic-workspaces', False)
        Gio.Settings.new('org.gnome.desktop.wm.preferences').set_int('num-workspaces', 4)
        Gio.Settings.new('org.gnome.desktop.wm.keybindings').set_strv('switch-to-workspace-right', ['<Control><Alt>Right'])
        Gio.Settings.sync()
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk
        Gtk.init()
        window = Gtk.Window(title='AJR portal test')
        window.present()
        drain(.4)
        call('TestFocus', GLib.Variant('(u)', (os.getpid(),)))
        drain(.4)
        before = call('TestState', result='(u)')[0]
        completed = []
        portal.send(65363, 12, lambda *args: completed.append(args))
        deadline = time.monotonic() + 4
        while not completed and time.monotonic() < deadline: drain(.1)
        assert completed == [(True, '')], completed
        drain(.5)
        assert call('TestState', result='(u)')[0] == before + 1, 'Portal input did not execute Linux shortcut'
        # The built-in Super action uses the public overview property, so it
        # continues to work even when the user's overlay-key is disabled.
        bus.call_sync('org.gnome.Shell', '/org/gnome/Shell', 'org.freedesktop.DBus.Properties', 'Set',
            GLib.Variant('(ssv)', ('org.gnome.Shell', 'OverviewActive', GLib.Variant('b', True))),
            None, Gio.DBusCallFlags.NONE, 1000, None)
        drain(.3)
        assert bus.call_sync('org.gnome.Shell', '/org/gnome/Shell', 'org.freedesktop.DBus.Properties', 'Get',
            GLib.Variant('(ss)', ('org.gnome.Shell', 'OverviewActive')), None, Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        bus.call_sync('org.gnome.Shell', '/org/gnome/Shell', 'org.freedesktop.DBus.Properties', 'Set',
            GLib.Variant('(ssv)', ('org.gnome.Shell', 'OverviewActive', GLib.Variant('b', False))),
            None, Gio.DBusCallFlags.NONE, 1000, None)
        portal.close()
        drain(.2)
        # Reopen in another process: a new D-Bus unique name must be able
        # to restore the saved token without asking the user again.
        restore_code = """
import sys, time
from gi.repository import GLib
sys.path.insert(0, sys.argv[1])
from keyboard_portal import KeyboardPortal
states = []
portal = KeyboardPortal(lambda *args: states.append(args))
portal.start()
deadline = time.monotonic() + 8
while portal.pending and time.monotonic() < deadline:
    while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
    time.sleep(.01)
assert portal.ready, ('Saved authorization did not restore in a new process', states)
portal.close()
"""
        restored = subprocess.Popen([sys.executable, '-c', restore_code, sys.argv[1]], stdout=log, stderr=subprocess.STDOUT)
        processes.append(restored)
        deadline = time.monotonic() + 10
        while restored.poll() is None and time.monotonic() < deadline: drain(.1)
        assert restored.poll() == 0, ('Permission was not restored without another dialog', states)
        window.destroy()
        assert shell.poll() is None and shell.pid == pid
        print('PASS real GNOME 46 portal: keyboard-only consent, workspace shortcut, persistent restore; Shell PID unchanged')
    finally:
        for process in reversed(processes):
            process.terminate()
            try: process.wait(timeout=4)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
'''


def main():
    with tempfile.TemporaryDirectory(prefix='ajr-portal-session-') as directory:
        root = Path(directory)
        runtime = root / 'runtime'
        runtime.mkdir(mode=0o700)
        shutil.copytree(BASE / 'extensao', root / 'source')
        env = dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / '.config'),
            XDG_DATA_HOME=str(root / '.local/share'), XDG_CACHE_HOME=str(root / '.cache'),
            XDG_RUNTIME_DIR=str(runtime), GSETTINGS_BACKEND='dconf',
            GNOME_SHELL_SESSION_MODE='user', XDG_CURRENT_DESKTOP='GNOME', LC_ALL='C.UTF-8',
            WAYLAND_DISPLAY='wayland-0', GDK_BACKEND='wayland', XDG_SESSION_TYPE='wayland',
            LIBGL_ALWAYS_SOFTWARE='1')
        for key in ('DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'AT_SPI_BUS_ADDRESS'): env.pop(key, None)
        with (root / 'driver.log').open('w') as driver_log:
            result = subprocess.run(['dbus-run-session', '--', sys.executable, '-c', DRIVER, str(BASE)],
                                    env=env, stdout=driver_log, stderr=driver_log, text=True, timeout=60)
        if result.returncode == 0:
            print('PASS real GNOME 46 portal: keyboard-only consent, workspace shortcut, overview and persistent restore; Shell PID unchanged')
        if (root / 'permission.png').exists():
            destination = BASE.parent / 'previews/beta9/portal-permission.png'
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / 'permission.png', destination)
        if result.returncode:
            print((root / 'driver.log').read_text())
            print((root / 'session.log').read_text())
        return result.returncode


if __name__ == '__main__': raise SystemExit(main())
