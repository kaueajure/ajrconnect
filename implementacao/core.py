"""Configuration, monitor identity and conservative connection profiles."""
from pathlib import Path
import copy
import json
import os
import re
import subprocess
import tempfile

APP_DIR = Path(__file__).resolve().parent
CFG_FILE = Path.home() / '.config/ajr-connect/config.json'
DATA_DIR = Path.home() / '.local/share/ajr-connect'
RUNTIME_DIR = Path(os.environ.get('XDG_RUNTIME_DIR', str(Path.home() / '.cache'))) / 'ajr-connect'
NATIVE = APP_DIR / 'ajr-freerdp'
DEFAULT = dict(server='', user='', shares=[], quality=0,
    monitor='0', monitor_connector='', fullscreen=False, capture_keyboard=True,
    clipboard=True, remember=False)


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_cfg():
    cfg = copy.deepcopy(DEFAULT)
    try:
        data = json.loads(CFG_FILE.read_text())
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in DEFAULT})
    except (OSError, ValueError):
        pass
    for key in ('server', 'user', 'monitor', 'monitor_connector'):
        cfg[key] = str(cfg[key]) if isinstance(cfg[key], (str, int)) else DEFAULT[key]
    for key in ('fullscreen', 'capture_keyboard', 'clipboard', 'remember'):
        cfg[key] = cfg[key] if isinstance(cfg[key], bool) else DEFAULT[key]
    try:
        cfg['quality'] = max(0, min(2, int(cfg['quality'])))
    except (ValueError, TypeError):
        cfg['quality'] = 0
    cfg['shares'] = [s for s in cfg.get('shares', []) if isinstance(s, dict)
                     and isinstance(s.get('name'), str) and isinstance(s.get('path'), str)] \
        if isinstance(cfg.get('shares'), list) else copy.deepcopy(DEFAULT['shares'])
    return cfg


def save_cfg(cfg):
    atomic_json(CFG_FILE, {k: cfg[k] for k in DEFAULT})


def detect_monitors():
    # FreeRDP indices are used only at launch. Connector names are persisted.
    binary = NATIVE if NATIVE.exists() else Path('/usr/bin/xfreerdp')
    output = subprocess.run([str(binary), '/monitor-list'], capture_output=True,
                            text=True, timeout=5)
    xrandr = subprocess.run(['xrandr', '--query'], capture_output=True,
                           text=True, timeout=5).stdout
    names = {}
    for line in xrandr.splitlines():
        m = re.match(r'(\S+) connected(?: primary)? (\d+)x(\d+)([+-]\d+)([+-]\d+)', line)
        if m:
            names[tuple(map(int, m.groups()[1:]))] = m.group(1)
    result = []
    for line in (output.stdout + output.stderr).splitlines():
        m = re.search(r'(\*)?\s*\[(\d+)\]\s+(\d+)x(\d+)\s+([+-]\d+)([+-]\d+)', line)
        if m:
            primary, idx, w, h, x, y = m.groups()
            geometry = tuple(map(int, (w, h, x, y)))
            connector = names.get(geometry)
            if connector:
                result.append(dict(id=idx, connector=connector, width=int(w),
                    height=int(h), x=int(x), y=int(y), primary=bool(primary)))
    return result


def resolve_monitor(cfg, monitors):
    connector = cfg.get('monitor_connector')
    if connector:
        return next((m for m in monitors if m['connector'] == connector), None)
    return next((m for m in monitors if m['id'] == str(cfg['monitor'])),
                next((m for m in monitors if m['primary']), None))


def window_geometry(monitor):
    # Preserve the remote aspect ratio, with space for GNOME decorations.
    scale = min(0.8, (monitor['width'] - 96) / monitor['width'],
                (monitor['height'] - 128) / monitor['height'])
    w, h = max(320, int(monitor['width'] * scale)), max(240, int(monitor['height'] * scale))
    return (monitor['x'] + (monitor['width'] - w) // 2,
            monitor['y'] + (monitor['height'] - h) // 2, w, h)


def build_command(cfg, monitor, native=NATIVE):
    x, y, w, h = window_geometry(monitor)
    cmd = [str(native), f"/v:{cfg['server']}", f"/u:{cfg['user']}",
           '/t:AJR Connect VM', '/wm-class:AJRConnect', '/cert:ignore',
           '/from-stdin:force', f"/monitors:{monitor['id']}",
           f"/w:{monitor['width']}", f"/h:{monitor['height']}",
           f'/smart-sizing:{w}x{h}', f'/window-position:{x}x{y}',
           '/network:broadband', '/gdi:sw',
           '/bpp:24' if cfg['quality'] == 2 else '/bpp:32',
           '+grab-keyboard' if cfg['capture_keyboard'] else '-grab-keyboard',
           '+clipboard' if cfg['clipboard'] else '-clipboard']
    if cfg['quality'] == 1:
        cmd.append('+window-drag')
    elif cfg['quality'] == 2:
        cmd += ['-wallpaper', '-themes', '-menu-anims']
    for share in cfg['shares']:
        path = str(Path(share['path']).expanduser().resolve())
        if ',' in path or ',' in share['name']:
            raise ValueError('O nome e o caminho da pasta não podem conter vírgulas.')
        cmd.append(f"/drive:{share['name']},{path}")
    return cmd


def host_port(value):
    value = value.strip()
    if value.startswith('['):
        match = re.fullmatch(r'\[([^]]+)\](?::(\d+))?', value)
        if not match:
            raise ValueError('Endereço IPv6 inválido.')
        host, port = match.group(1), int(match.group(2) or 3389)
    elif value.count(':') == 1:
        host, port_text = value.rsplit(':', 1)
        port = int(port_text)
    else:
        host, port = value, 3389
    if not host or not 1 <= port <= 65535:
        raise ValueError('Informe um servidor e uma porta válida.')
    return host, port
