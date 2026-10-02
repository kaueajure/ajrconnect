#!/usr/bin/env python3
"""Enable v6 at login, allowing time for GNOME to discover its extensions."""
import time
from gi.repository import Gio, GLib

uuid = 'ajr-connect@ajure.local'
for attempt in range(10):
    try:
        info = Gio.bus_get_sync(Gio.BusType.SESSION, None).call_sync('org.gnome.Shell', '/org/gnome/Shell',
            'org.gnome.Shell.Extensions', 'GetExtensionInfo', GLib.Variant('(s)', (uuid,)),
            None, Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
        if info.get('version', 0) >= 6:
            enabled = Gio.bus_get_sync(Gio.BusType.SESSION, None).call_sync('org.gnome.Shell', '/org/gnome/Shell',
                'org.gnome.Shell.Extensions', 'EnableExtension', GLib.Variant('(s)', (uuid,)),
                None, Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
            if enabled:
                break
        elif info:
            break  # The old cached module must stay disabled until logout.
    except GLib.Error:
        pass
    time.sleep(1)
