#!/usr/bin/env python3
"""Read-only checks of package files and actual runtime dependencies."""
from dataclasses import dataclass
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import sys

BASE = Path(__file__).resolve().parent
FILES = ('ajr_app.py', 'ui.py', 'dialogs.py', 'keyboard.py', 'assets/style.css', 'assets/ajr-connect.svg', 'assets/workspace.svg',
         'core.py', 'integration.py', 'x11.py', 'ajr-control', 'ajr-connect',
         'dependencies.py',
         'version.py', 'reconnect.py', 'updates.py', 'update_dialog.py',
         'ajr-connect.desktop.in',
         'enable-extension.py', 'extensao/extension.js', 'extensao/integration.js', 'extensao/stylesheet.css',
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


def collect_package_checks(base=BASE):
    checks = []
    checks.append(Check('Usuário', os.geteuid() != 0,
                        'A instalação é por usuário.',
                        'Execute no terminal da sua sessão, sem sudo.'))
    missing = [name for name in FILES if not (base / name).is_file()]
    checks.append(Check('Arquivos do pacote', not missing,
                        'Ausentes: ' + ', '.join(missing) if missing else 'Componentes presentes.',
                        'Extraia novamente o pacote completo; ele deve incluir o cliente já compilado.'))
    binary = base / 'native/ajr-freerdp'
    machine = platform.machine().lower()
    expected = {'x86_64': (2, 62), 'amd64': (2, 62), 'aarch64': (2, 183),
                'arm64': (2, 183), 'i386': (1, 3), 'i686': (1, 3),
                'armv7l': (1, 40)}.get(machine)
    try:
        with binary.open('rb') as stream:
            header = stream.read(20)
        valid = (len(header) == 20 and header[:4] == b'\x7fELF'
                 and header[5] in (1, 2))
        actual = (header[4], int.from_bytes(header[18:20],
                  'little' if header[5] == 1 else 'big')) if valid else None
    except OSError:
        actual = None
    checks.append(Check('Arquitetura do cliente', platform.system() == 'Linux'
                        and expected is not None and actual == expected,
                        f'Sistema: {platform.system()} {machine}; ELF do cliente: {actual}.',
                        'Use um pacote compilado para sua arquitetura ou compile os fontes '
                        'com python3 native/build.py. O download publicado é Linux x86_64.'))
    return checks


def check_package(base=BASE):
    checks = collect_package_checks(base)
    for check in checks:
        if not check.ok:
            print('FALHA — ' + check.name + ': ' + check.detail)
            print('  Como resolver: ' + check.remedy)
    return all(check.ok for check in checks)


def collect_checks(base=BASE):
    checks = collect_package_checks(base)
    for command, package in [('xrandr', 'x11-xserver-utils'),
                             ('secret-tool', 'libsecret-tools')]:
        checks.append(Check(command, shutil.which(command) is not None,
                            'Disponível.' if shutil.which(command) else 'Comando ausente.',
                            'Instale a dependência: sudo apt install ' + package))
    for name, code, remedy in [
        ('Interface Python', GI_PROBE,
         'Verifique os pacotes python3-gi, gir1.2-gtk-4.0 e gir1.2-adw-1.'),
        ('Bibliotecas RDP', LIBRARY_PROBE,
         'Instale libfreerdp2-2t64, libfreerdp-client2-2t64 e libwinpr2-2t64 na versão 2.11.5; '
         'não substitua bibliotecas por versões diferentes.')]:
        ok, detail = run([sys.executable, '-c', code])
        checks.append(Check(name, ok, detail, remedy))
    if all(check.ok for check in checks[:3]):
        ok, detail = run(['ldd', str(base / 'native/ajr-freerdp')])
        checks.append(Check('Bibliotecas do cliente', ok and 'not found' not in detail,
                            'Bibliotecas resolvidas.' if ok and 'not found' not in detail else detail,
                            'Verifique as bibliotecas exigidas pelo binário, incluindo glibc, '
                            'e a disponibilidade de ldd. Se necessário, compile neste sistema.'))
    return checks


def check_compatibility(base=BASE):
    checks = collect_checks(base)
    print('AJR Connect — verificação de dependências (sem alterações)')
    for check in checks:
        print(('OK' if check.ok else 'FALHA') + ' — ' + check.name + ': ' + check.detail)
        if not check.ok and check.remedy:
            print('  Como resolver: ' + check.remedy)
    compatible = all(check.ok for check in checks)
    print('\n' + ('Dependências disponíveis.' if compatible else
                  'Dependências ausentes ou incompatíveis. Resolva as falhas acima.'))
    return compatible


if __name__ == '__main__':
    sys.exit(0 if check_compatibility() else 1)
