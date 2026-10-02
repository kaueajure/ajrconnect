#!/usr/bin/env python3
"""Restore the most recent installation backup, including GNOME settings."""
from pathlib import Path
import json
import shutil
import subprocess
from gi.repository import Gio
from install import lookup_settings

home = Path.home()
data = home / '.local/share/ajr-connect'
installation = json.loads((data / 'last-install.json').read_text())
backup = Path(installation['backup'])
uuid = 'ajr-connect@ajure.local'
if installation.get('extension_managed', True):
    subprocess.run(['gnome-extensions', 'disable', uuid], check=False)
for name, target in [('ajr-connect', home / '.local/bin/ajr-connect'),
                     ('config.json', home / '.config/ajr-connect/config.json')]:
    if (backup / name).exists():
        shutil.copy2(backup / name, target)
    elif name == 'ajr-connect' and installation.get('launcher_managed'):
        target.unlink(missing_ok=True)
for name, target in [('extension', home / '.local/share/gnome-shell/extensions' / uuid),
                     ('app', data / 'app')]:
    if name == 'extension' and not installation.get('extension_managed', True):
        continue
    if target.exists():
        shutil.rmtree(target)
    if (backup / name).exists():
        shutil.copytree(backup / name, target)
if installation.get('desktop_managed'):
    desktop = home / '.local/share/applications/ajr-connect.desktop'
    if (backup / 'application.desktop').exists():
        desktop.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup / 'application.desktop', desktop)
    else:
        desktop.unlink(missing_ok=True)
autostart = home / '.config/autostart/ajr-connect-integration.desktop'
if installation.get('autostart_managed', True):
    if (backup / 'autostart.desktop').exists():
        shutil.copy2(backup / 'autostart.desktop', autostart)
    else:
        autostart.unlink(missing_ok=True)
settings = json.loads((backup / 'settings.json').read_text())
wm = lookup_settings(Gio, 'org.gnome.desktop.wm.keybindings')
if wm is not None and 'toggle-fullscreen' in settings:
    wm.set_strv('toggle-fullscreen', settings['toggle-fullscreen'])
shell = lookup_settings(Gio, 'org.gnome.shell')
for key in ('enabled-extensions', 'disabled-extensions'):
    if shell is not None and key in settings:
        shell.set_strv(key, settings[key])
Gio.Settings.sync()
print('Backup restaurado:', backup)
if installation.get('extension_managed', True):
    print('Saia da sessão e entre novamente para carregar a extensão restaurada.')
