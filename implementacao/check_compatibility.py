#!/usr/bin/env python3
"""Read-only checks for the first supported AJR Connect distribution target."""
from dataclasses import dataclass
from pathlib import Path
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys

BASE = Path(__file__).resolve().parent
FILES = ('ajr_app.py', 'core.py', 'x11.py', 'ajr-control', 'ajr-connect',
         'dependencies.py',
         'ajr-connect.desktop.in',
         'enable-extension.py', 'extensao/extension.js', 'extensao/stylesheet.css',
         'extensao/metadata.json', 'native/ajr-freerdp')


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    remedy: str = ''


def run(command):
    """Keep native/GI failures isolated and bound every external probe."""
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=10, errors='replace')
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)


def read_os_release(path=Path('/etc/os-release')):
    values = {}
    for line in path.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            parts = shlex.split(value)
            values[key] = parts[0] if parts else ''
    return values


def supported_os(values):
    # Zorin 18.1 reports VERSION_ID=18 and VERSION=18.1.
    return (values.get('ID') == 'zorin'
            and values.get('VERSION', '').split(' ', 1)[0] == '18.1')


GI_PROBE = '''
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio
assert all(hasattr(Adw, name) for name in (
    'ToolbarView', 'SwitchRow', 'PasswordEntryRow', 'EntryRow', 'ComboRow'))
print('GTK %s.%s; libadwaita %s.%s' % (
    Gtk.get_major_version(), Gtk.get_minor_version(),
    Adw.get_major_version(), Adw.get_minor_version()))
'''

SHELL_PROBE = '''
import gi
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
reply = bus.call_sync('org.gnome.Shell', '/org/gnome/Shell',
    'org.freedesktop.DBus.Properties', 'Get',
    GLib.Variant('(ss)', ('org.gnome.Shell', 'ShellVersion')),
    None, Gio.DBusCallFlags.NONE, 5000, None)
version = reply.get_child_value(0).get_variant().get_string()
assert version.split('.')[0] == '46', 'GNOME ativo: ' + version
source = Gio.SettingsSchemaSource.get_default()
for schema, keys in {
    'org.gnome.desktop.wm.keybindings': ('toggle-fullscreen',),
    'org.gnome.shell': ('enabled-extensions', 'disabled-extensions'),
}.items():
    item = source.lookup(schema, True)
    assert item is not None and all(item.has_key(key) for key in keys), schema
print('GNOME Shell ativo ' + version + '; D-Bus e esquemas disponíveis')
'''

LIBRARY_PROBE = '''
import ctypes
for name, symbol in [('libfreerdp2.so.2', 'freerdp_get_version_string'),
                     ('libwinpr2.so.2', 'winpr_get_version_string')]:
    library = ctypes.CDLL(name)
    version = getattr(library, symbol)
    version.restype = ctypes.c_char_p
    value = version().decode()
    assert value == '2.11.5', name + ': ' + value + ' (esperado 2.11.5)'
    print(name + ': ' + value)
ctypes.CDLL('libfreerdp-client2.so.2')
'''


def collect_checks(base=BASE):
    checks = []
    checks.append(Check('Usuário', os.geteuid() != 0,
                        'A instalação é por usuário.',
                        'Execute no terminal da sua sessão, sem sudo.'))
    try:
        release = read_os_release()
        checks.append(Check('Sistema', supported_os(release),
                            release.get('PRETTY_NAME', 'Sistema desconhecido'),
                            'Esta versão foi preparada para Zorin OS 18.1.'))
    except (OSError, ValueError) as error:
        checks.append(Check('Sistema', False, str(error),
                            'Não foi possível identificar /etc/os-release.'))
    machine = platform.machine()
    checks.append(Check('Arquitetura', platform.system() == 'Linux' and machine == 'x86_64',
                        platform.system() + ' ' + machine,
                        'Use Zorin OS 18.1 em arquitetura x86_64.'))
    session = os.environ.get('XDG_SESSION_TYPE', '')
    checks.append(Check('Sessão gráfica', session == 'wayland'
                        and bool(os.environ.get('WAYLAND_DISPLAY'))
                        and bool(os.environ.get('DISPLAY')),
                        'Tipo: ' + (session or 'não identificado'),
                        'Abra um terminal dentro da sessão GNOME Wayland, com XWayland disponível.'))
    missing = [name for name in FILES if not (base / name).is_file()]
    checks.append(Check('Arquivos do pacote', not missing,
                        'Ausentes: ' + ', '.join(missing) if missing else 'Componentes presentes.',
                        'Extraia novamente o pacote completo; ele deve incluir o cliente já compilado.'))
    for command, package in [('gnome-extensions', 'gnome-shell'),
                             ('xrandr', 'x11-xserver-utils'),
                             ('secret-tool', 'libsecret-tools')]:
        checks.append(Check(command, shutil.which(command) is not None,
                            'Disponível.' if shutil.which(command) else 'Comando ausente.',
                            'Instale a dependência: sudo apt install ' + package))
    for name, code, remedy in [
        ('Interface Python', GI_PROBE,
         'Verifique os pacotes python3-gi, gir1.2-gtk-4.0 e gir1.2-adw-1.'),
        ('GNOME ativo', SHELL_PROBE,
         'Execute na sessão GNOME 46 do usuário; ela precisa oferecer D-Bus e seus esquemas.'),
        ('Bibliotecas RDP', LIBRARY_PROBE,
         'Instale libfreerdp2-2t64, libfreerdp-client2-2t64 e libwinpr2-2t64 na versão 2.11.5; '
         'não substitua bibliotecas por versões diferentes.')]:
        ok, detail = run([sys.executable, '-c', code])
        checks.append(Check(name, ok, detail, remedy))
    binary = base / 'native/ajr-freerdp'
    if binary.is_file():
        ok, detail = run([str(binary), '/version'])
        checks.append(Check('Cliente AJR', ok and bool(re.search(r'version 2\.11\.5(?:\s|$)', detail)),
                            detail, 'Verifique as bibliotecas exigidas pelo executável e sua permissão de execução.'))
    # Query XWayland without launching an RDP connection or exposing credentials.
    ok, detail = run(['xrandr', '--query'])
    connected = bool(re.search(r'^\S+ connected(?: primary)? \d+x\d+[+-]\d+[+-]\d+',
                               detail, re.MULTILINE))
    checks.append(Check('XWayland e monitores', ok and connected,
                        'Monitor ativo acessível.' if ok and connected else detail,
                        'Verifique XWayland e o acesso ao DISPLAY na sessão gráfica.'))
    if binary.is_file() and ok and connected:
        native_ok, native_output = run([str(binary), '/monitor-list'])
        geometries = {tuple(map(int, match)) for match in re.findall(
            r'^\S+ connected(?: primary)? (\d+)x(\d+)([+-]\d+)([+-]\d+)',
            detail, re.MULTILINE)}
        native_geometries = {tuple(map(int, match)) for match in re.findall(
            r'\[\d+\]\s+(\d+)x(\d+)\s+([+-]\d+)([+-]\d+)', native_output)}
        checks.append(Check('Seleção de monitor', native_ok and bool(geometries & native_geometries),
                            'Mapeamento AJR/XRandR disponível.' if native_ok and geometries & native_geometries
                            else 'O cliente não encontrou um monitor correspondente ao XRandR.',
                            'Verifique a configuração dos monitores e o acesso do cliente ao XWayland.'))
    return checks


def check_compatibility(base=BASE):
    checks = collect_checks(base)
    print('AJR Connect — verificação de compatibilidade (sem alterações)')
    for check in checks:
        print(('OK' if check.ok else 'FALHA') + ' — ' + check.name + ': ' + check.detail)
        if not check.ok and check.remedy:
            print('  Como resolver: ' + check.remedy)
    compatible = all(check.ok for check in checks)
    print('\n' + ('Ambiente compatível com o alvo definido.' if compatible else
                  'Instalação bloqueada. Resolva as falhas acima e execute novamente.'))
    return compatible


if __name__ == '__main__':
    sys.exit(0 if check_compatibility() else 1)
