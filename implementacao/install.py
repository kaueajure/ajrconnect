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
import re
import fcntl
from core import atomic_json
from version import APP_VERSION
from check_compatibility import check_compatibility, check_package
from dependencies import ensure_dependencies
from integration import install_extension, refresh_integration

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
UPDATE_JOURNAL = DATA / 'update-in-progress.json'
UPDATING = False

def install(updating=False):
    global UPDATING
    UPDATING = updating
    if not check_package(BASE):
        return 1
    if not updating and not ensure_dependencies():
        return 1
    # Complete all read-only checks before creating backups or changing settings.
    if not check_compatibility(BASE):
        return 1
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / '.install.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Outra instalação já está em andamento. Aguarde e tente novamente.')
            return 1
        if UPDATE_JOURNAL.exists():
            recover_update()
        try:
            return install_files()
        except Exception as exc:
            if not updating:
                raise
            print('Falha na atualização:', exc)
            try:
                recover_update()
                print('A instalação anterior foi preservada.')
            except Exception as recovery_error:
                print('Falha ao restaurar o backup:', recovery_error)
            return 1


def recover_update():
    if not UPDATE_JOURNAL.exists():
        return
    from gi.repository import Gio
    backup = Path(json.loads(UPDATE_JOURNAL.read_text())['backup']).resolve()
    if backup.parent != (DATA / 'backups').resolve() or not (backup / 'settings.json').is_file():
        raise ValueError('Backup de atualização inválido.')
    for name, target in [('app', APP), ('extension', EXT)]:
        if target.exists():
            shutil.rmtree(target)
        if (backup / name).exists():
            shutil.copytree(backup / name, target)
    for name, target in [('ajr-connect', BIN), ('application.desktop', DESKTOP),
                         ('autostart.desktop', HOME / '.config/autostart/ajr-connect-integration.desktop'),
                         ('last-install.json', DATA / 'last-install.json')]:
        if (backup / name).is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup / name, target)
        else:
            target.unlink(missing_ok=True)
    state = json.loads((backup / 'settings.json').read_text())
    for schema, keys in [('org.gnome.desktop.wm.keybindings', ('toggle-fullscreen',)),
                         ('org.gnome.shell', ('enabled-extensions', 'disabled-extensions'))]:
        settings = lookup_settings(Gio, schema)
        if settings:
            for key in keys:
                if key in state:
                    settings.set_strv(key, state[key])
    Gio.Settings.sync()
    if (EXT / 'bridge.json').is_file():
        refresh_integration(json.loads((EXT / 'bridge.json').read_text())['revision'])
    UPDATE_JOURNAL.unlink()


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


def lookup_settings(Gio, schema):
    source = Gio.SettingsSchemaSource.get_default()
    if source is None or source.lookup(schema, True) is None:
        return None
    return Gio.Settings.new(schema)


def extension_supported():
    if not shutil.which('gnome-shell') or not shutil.which('gnome-extensions'):
        return False
    try:
        result = subprocess.run(['gnome-shell', '--version'], capture_output=True,
                                text=True, timeout=5)
        if result.returncode or not isinstance(result.stdout, str):
            return False
        match = re.search(r'GNOME Shell (\d+)', result.stdout)
        metadata = json.loads((BASE / 'extensao/metadata.json').read_text())
        return bool(match and match.group(1) in metadata.get('shell-version', []))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def install_files():
    from gi.repository import Gio
    BACKUP.mkdir(parents=True, mode=0o700)
    for source, name in [(BIN, 'ajr-connect'), (CFG, 'config.json'), (DESKTOP, 'application.desktop'),
                         (DATA / 'last-install.json', 'last-install.json'),
                         (HOME / '.config/autostart/ajr-connect-integration.desktop', 'autostart.desktop')]:
        if source.exists():
            shutil.copy2(source, BACKUP / name)
    if EXT.exists():
        shutil.copytree(EXT, BACKUP / 'extension')
    if APP.exists():
        shutil.copytree(APP, BACKUP / 'app')
    wm = lookup_settings(Gio, 'org.gnome.desktop.wm.keybindings')
    shell = lookup_settings(Gio, 'org.gnome.shell')
    extension_managed = shell is not None and extension_supported()
    state = {}
    if wm is not None:
        state['toggle-fullscreen'] = wm.get_strv('toggle-fullscreen')
    if extension_managed:
        state['enabled-extensions'] = shell.get_strv('enabled-extensions')
        state['disabled-extensions'] = shell.get_strv('disabled-extensions')
    (BACKUP / 'settings.json').write_text(json.dumps(state, indent=2))
    if UPDATING:
        atomic_json(UPDATE_JOURNAL, dict(backup=str(BACKUP)))
    APP.mkdir(parents=True, exist_ok=True)
    for name in ('ajr_app.py', 'ui.py', 'dialogs.py', 'keyboard.py', 'reconnect.py', 'updates.py',
                 'update_dialog.py', 'version.py', 'core.py', 'integration.py', 'x11.py', 'ajr-control', 'enable-extension.py'):
        shutil.copy2(BASE / name, APP / name)
    shutil.copytree(BASE / 'assets', APP / 'assets', dirs_exist_ok=True)
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
        '@AJR_LAUNCHER@', desktop_exec(sys.executable, BIN)).replace(
        '@AJR_ICON@', str(APP / 'assets/ajr-connect.svg').replace('\\', '\\\\')))
    DESKTOP.chmod(0o644)
    if extension_managed:
        had_bridge = (EXT / 'bridge.json').is_file()
        manifest, loader_changed = install_extension(BASE / 'extensao', EXT)
    # Remove only the conflicting shortcut, leaving other user bindings intact.
    if wm is not None:
        wm.set_strv('toggle-fullscreen', [key for key in state['toggle-fullscreen']
                                        if key.lower() not in ('<ctrl><alt>return', '<control><alt>return')])
    integration_status = 'unavailable'
    if extension_managed:
        autostart = HOME / '.config/autostart/ajr-connect-integration.desktop'
        autostart.parent.mkdir(parents=True, exist_ok=True)
        if autostart.exists():
            shutil.copy2(autostart, BACKUP / 'autostart.desktop')
        autostart.write_text('[Desktop Entry]\nType=Application\nName=AJR Connect Integration\n'
            'Exec=' + desktop_exec(sys.executable, APP / 'enable-extension.py') + '\n'
            'OnlyShowIn=GNOME;\nX-GNOME-Autostart-enabled=true\nNoDisplay=true\n')
        integration_status = refresh_integration(manifest['revision'])
        if had_bridge and loader_changed and integration_status == 'ready':
            integration_status = 'loader-restart-required'
    Gio.Settings.sync()
    (DATA / 'last-install.json').write_text(json.dumps({'version': 6, 'release': APP_VERSION, 'backup': str(BACKUP),
        'needs_shell_restart': integration_status in ('restart-required', 'loader-restart-required', 'not-discovered'),
        'integration_status': integration_status,
        'bridge_loader_changed': loader_changed if extension_managed else False,
        'desktop_managed': True,
        'launcher_managed': True, 'extension_managed': extension_managed,
        'autostart_managed': extension_managed}, indent=2))
    if UPDATING:
        UPDATE_JOURNAL.unlink(missing_ok=True)
    print('Instalado em:', APP)
    print('Backup:', BACKUP)
    print('Feche e abra o AJR Connect para usar o aplicativo atualizado. Reconecte o Windows para usar o cliente atualizado.')
    if integration_status == 'ready':
        print('AJR Bar atualizada na sessão atual. Não é necessário sair do Zorin.')
    elif integration_status == 'restart-required':
        print('O aplicativo já está atualizado. A troca da extensão antiga pela ponte recarregável exige uma nova entrada na sessão; as próximas atualizações da barra não exigirão isso.')
    elif integration_status == 'loader-restart-required':
        print('A parte fixa da integração mudou. Essa alteração excepcional precisa de uma nova entrada na sessão para concluir a atualização da barra.')
    elif integration_status == 'not-discovered':
        print('Aplicativo instalado. Para usar a AJR Bar pela primeira vez, entre novamente na sessão; as próximas atualizações serão aplicadas na sessão atual.')
    elif integration_status == 'failed':
        print('O aplicativo foi atualizado, mas a AJR Bar não confirmou a atualização. Use os controles do aplicativo e execute o instalador novamente para repetir a tentativa.')
    elif extension_managed:
        print('Aplicativo atualizado. A AJR Bar será ativada na próxima entrada no desktop; os controles do aplicativo já estão disponíveis.')
    else:
        print('AJR Bar indisponível neste desktop. Use os controles do aplicativo e Ctrl+Alt+Enter.')
    return 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Instalador por usuário do AJR Connect')
    parser.add_argument('--check', action='store_true', help='Apenas verificar dependências, sem instalar')
    parser.add_argument('--update', action='store_true', help='Atualizar sem instalar dependências nem solicitar sudo')
    parser.add_argument('--recover-update', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.recover_update:
        recover_update()
        raise SystemExit(0)
    raise SystemExit((0 if check_compatibility(BASE) else 1) if args.check else install(updating=args.update))
