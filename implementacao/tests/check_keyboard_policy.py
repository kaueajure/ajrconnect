#!/usr/bin/env python3
"""Build a frontend harness and run it without connecting to the user's VM."""
from pathlib import Path
import os
import runpy
import shutil
import subprocess
from unittest.mock import patch

base = Path(__file__).resolve().parent
native = base.parent / 'native'
commands = []
with patch('subprocess.run', lambda command, **kwargs: commands.append(command)):
    runpy.run_path(str(native / 'build.py'))
command = commands[0]
command = [str(base / 'keyboard_policy.c') if value.endswith('/cli/xfreerdp.c')
           else str(base / 'keyboard-policy') if value == str(native / 'ajr-freerdp')
           else value for value in command]
subprocess.run(command, check=True)
sdk = base / 'tools/sdk'
xvfb = Path(shutil.which('Xvfb') or sdk / 'usr/bin/Xvfb')
if not xvfb.exists():
    raise RuntimeError('Instale Xvfb ou extraia xvfb e libxfont2 em tests/tools/sdk para este teste isolado.')
env = dict(os.environ, LD_LIBRARY_PATH=str(sdk / 'usr/lib/x86_64-linux-gnu'))
server = subprocess.Popen([str(xvfb), '-displayfd', '1', '-screen', '0', '800x600x24',
    '-nolisten', 'tcp', '-noreset', '-ac'], env=env, stdout=subprocess.PIPE, text=True)
try:
    display = server.stdout.readline().strip()
    assert display, 'O servidor X de teste não iniciou'
    env['DISPLAY'] = ':' + display
    subprocess.run([str(base / 'keyboard-policy')], env=env, check=True, timeout=10)
finally:
    server.terminate()
    server.wait(timeout=5)
    server.stdout.close()
