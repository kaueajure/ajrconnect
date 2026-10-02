#!/usr/bin/env python3
"""Restore the most recent installation backup, including GNOME settings."""
from pathlib import Path
import json
import shutil
import subprocess
from gi.repository import Gio

home = Path.home()
data = home / '.local/share/ajr-connect'
installation = json.loads((data / 'last-install.json').read_text())
backup = Path(installation['backup'])
uuid = 'ajr-connect@ajure.local'
subprocess.run(['gnome-extensions', 'disable', uuid], check=False)
for name, target in [('ajr-connect', home / '.local/bin/ajr-connect'),
                     ('config.json', home / '.config/ajr-connect/config.json')]:
    if (backup / name).exists():
        shutil.copy2(backup / name, target)
    elif name == 'ajr-connect' and installation.get('launcher_managed'):
        target.unlink(missing_ok=True)
for name, target in [('extension', home / '.local/share/gnome-shell/extensions' / uuid),
                     ('app', data / 'app')]:
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
if (backup / 'autostart.desktop').exists():
    shutil.copy2(backup / 'autostart.desktop', autostart)
else:
    autostart.unlink(missing_ok=True)
settings = json.loads((backup / 'settings.json').read_text())
wm = Gio.Settings.new('org.gnome.desktop.wm.keybindings')
wm.set_strv('toggle-fullscreen', settings['toggle-fullscreen'])
shell = Gio.Settings.new('org.gnome.shell')
for key in ('enabled-extensions', 'disabled-extensions'):
    shell.set_strv(key, settings[key])
Gio.Settings.sync()
print('Backup restaurado:', backup)
print('Saia da sessão GNOME e entre novamente para carregar a extensão restaurada.')
