#!/usr/bin/env python3
"""Activate the stable bridge when GNOME becomes available after login."""
import time
from integration import installed_revision, refresh_integration

revision = installed_revision()
if revision:
    for attempt in range(10):
        status = refresh_integration(revision, timeout=1)
        if status in ('ready', 'restart-required'):
            break
        time.sleep(1)
