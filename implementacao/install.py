#!/usr/bin/env python3
"""Install AJR per-user, preserving the original package and creating a rollback."""
from pathlib import Path
from datetime import datetime
import json
import os
import shutil
import subprocess
import argparse
import sys
import tempfile
from check_compatibility import check_compatibility
from dependencies import ensure_dependencies

BASE = Path(__file__).resolve().parent
HOME = Path.home()
UUID = 'ajr-connect@ajure.local'
DATA = HOME / '.local/share/ajr-connect'
APP = DATA / 'app'
EXT = HOME / '.local/share/gnome-shell/extensions' / UUID
BIN = HOME / '.local/bin/ajr-connect'
CFG = HOME / '.config/ajr-connect/config.json'
DESKTOP = HOME / '.local/share/applications/ajr-connect.desktop'
BACKUP = DATA / 'backups' / ('v6-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))

def install():
    if not ensure_dependencies():
        return 1
    # Complete all read-only checks before creating backups or changing settings.
    if not check_compatibility(BASE):
        return 1
    return install_files()


def desktop_exec(*arguments):
    """Quote each argument according to Desktop Entry Exec syntax, not shell syntax."""
    result = []
    for argument in arguments:
        value = str(argument)
        if '\n' in value or '\r' in value:
            raise ValueError('O caminho não pode conter quebras de linha.')
        value = value.replace('%', '%%')
        for character in ('\\', '"', '`', '$'):
            value = value.replace(character, '\\' + character)
        # Backslashes are escaped again for the desktop file string value.
        result.append('"' + value.replace('\\', '\\\\') + '"')
    return ' '.join(result)


def install_files():
    from gi.repository import Gio
    BACKUP.mkdir(parents=True, mode=0o700)
    for source, name in [(BIN, 'ajr-connect'), (CFG, 'config.json'), (DESKTOP, 'application.desktop')]:
        if source.exists():
            shutil.copy2(source, BACKUP / name)
    if EXT.exists():
        shutil.copytree(EXT, BACKUP / 'extension')
    if APP.exists():
        shutil.copytree(APP, BACKUP / 'app')
    wm = Gio.Settings.new('org.gnome.desktop.wm.keybindings')
    shell = Gio.Settings.new('org.gnome.shell')
    state = {'toggle-fullscreen': wm.get_strv('toggle-fullscreen'),
             'enabled-extensions': shell.get_strv('enabled-extensions'),
             'disabled-extensions': shell.get_strv('disabled-extensions')}
    (BACKUP / 'settings.json').write_text(json.dumps(state, indent=2))
    subprocess.run(['gnome-extensions', 'disable', UUID], check=False)
    APP.mkdir(parents=True, exist_ok=True)
    for name in ('ajr_app.py', 'core.py', 'x11.py', 'ajr-control', 'enable-extension.py'):
        shutil.copy2(BASE / name, APP / name)
    # Replacing the inode permits an existing RDP process to finish normally.
    fd, temporary = tempfile.mkstemp(prefix='.ajr-freerdp-', dir=APP)
    os.close(fd)
    try:
        shutil.copy2(BASE / 'native/ajr-freerdp', temporary)
        os.chmod(temporary, 0o755)
        os.replace(temporary, APP / 'ajr-freerdp')
    finally:
        Path(temporary).unlink(missing_ok=True)
    for name in ('ajr-control', 'ajr-freerdp'):
        (APP / name).chmod(0o755)
    if (BASE / 'licenses').is_dir():
        shutil.copytree(BASE / 'licenses', APP / 'licenses', dirs_exist_ok=True)
    if (BASE / 'NOTICE.txt').is_file():
        shutil.copy2(BASE / 'NOTICE.txt', APP / 'NOTICE.txt')
    if (BASE / 'LICENSE').is_file():
        shutil.copy2(BASE / 'LICENSE', APP / 'LICENSE')
    BIN.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BASE / 'ajr-connect', BIN)
    BIN.chmod(0o755)
    DESKTOP.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP.write_text((BASE / 'ajr-connect.desktop.in').read_text().replace(
        '@AJR_LAUNCHER@', desktop_exec(sys.executable, BIN)))
    DESKTOP.chmod(0o644)
    EXT.mkdir(parents=True, exist_ok=True)
    for name in ('extension.js', 'stylesheet.css', 'metadata.json'):
        shutil.copy2(BASE / 'extensao' / name, EXT / name)
    # Remove only the conflicting shortcut, leaving other user bindings intact.
    wm.set_strv('toggle-fullscreen', [key for key in state['toggle-fullscreen']
                                    if key.lower() not in ('<ctrl><alt>return', '<control><alt>return')])
    # A loaded ES module cannot be replaced in this Wayland session.
    # Keep v5 disabled; the autostart enables only metadata version >= 6.
    subprocess.run(['gnome-extensions', 'disable', UUID], check=False)
    autostart = HOME / '.config/autostart/ajr-connect-integration.desktop'
    autostart.parent.mkdir(parents=True, exist_ok=True)
    if autostart.exists():
        shutil.copy2(autostart, BACKUP / 'autostart.desktop')
    autostart.write_text('[Desktop Entry]\nType=Application\nName=AJR Connect Integration\n'
        'Exec=' + desktop_exec(sys.executable, APP / 'enable-extension.py') + '\n'
        'X-GNOME-Autostart-enabled=true\nNoDisplay=true\n')
    Gio.Settings.sync()
    (DATA / 'last-install.json').write_text(json.dumps({'version': 6, 'backup': str(BACKUP),
        'needs_shell_restart': True, 'desktop_managed': True,
        'launcher_managed': True}, indent=2))
    print('Instalado em:', APP)
    print('Backup:', BACKUP)
    print('O GNOME 46 mantém o módulo antigo em cache. Saia da sessão e entre novamente para carregar a AJR Bar v6.')
    return 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Instalador por usuário do AJR Connect')
    parser.add_argument('--check', action='store_true', help='Apenas verificar compatibilidade, sem instalar')
    args = parser.parse_args()
    raise SystemExit((0 if check_compatibility(BASE) else 1) if args.check else install())
