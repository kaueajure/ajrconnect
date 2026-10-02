#!/usr/bin/env python3
"""Build only the X11 frontend against the installed 2.11.5 ABI. No sudo."""
from pathlib import Path
import subprocess
import os

BASE = Path(__file__).resolve().parent
SRC = BASE / 'vendor/FreeRDP-2.11.5/client/X11'
FILES = [str(p) for p in sorted(SRC.glob('*.c'))
         if p.name not in ('xf_tsmf.c', 'generate_argument_docbook.c')]
FILES += [str(SRC / 'cli/xfreerdp.c'), str(BASE / 'ajr.c')]
cmd = ['gcc', '-O2', '-g', '-Wall', '-Wno-deprecated-declarations',
       '-Wno-unused-but-set-variable', '-DWITH_XRENDER', '-DWITH_XRANDR',
       '-DWITH_XINERAMA', '-DWITH_XCURSOR', '-DWITH_XFIXES', '-DWITH_XEXT']
if os.environ.get('AJR_BUILD_RELEASE') == '1':
    cmd.append('-ffile-prefix-map=' + str(BASE.parent) + '=/usr/src/ajr-connect')
for p in (BASE, SRC, BASE / 'sdk/usr/include/freerdp2',
          BASE / 'sdk/usr/include/winpr2', BASE / 'vendor/FreeRDP-2.11.5/resources'):
    cmd.append('-I' + str(p))
cmd += FILES + ['-o', os.environ.get('AJR_BUILD_OUTPUT', str(BASE / 'ajr-freerdp')),
               '-l:libfreerdp-client2.so.2', '-l:libfreerdp2.so.2', '-l:libwinpr2.so.2',
               '-lX11', '-lXrender', '-lXrandr', '-lXinerama', '-lXcursor',
               '-lXfixes', '-lXext', '-lm', '-lrt', '-lpthread']
subprocess.run(cmd, check=True)
