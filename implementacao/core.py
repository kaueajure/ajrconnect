"""Configuration, monitor identity and conservative connection profiles."""
from pathlib import Path
import copy
import json
import os
import re
import subprocess
import tempfile
import uuid

APP_DIR = Path(__file__).resolve().parent
CFG_FILE = Path.home() / '.config/ajr-connect/config.json'
DATA_DIR = Path.home() / '.local/share/ajr-connect'
RUNTIME_DIR = Path(os.environ.get('XDG_RUNTIME_DIR', str(Path.home() / '.cache'))) / 'ajr-connect'
NATIVE = APP_DIR / 'ajr-freerdp'
if not NATIVE.exists():
    NATIVE = APP_DIR / 'native/ajr-freerdp'
DEFAULT = dict(server='', user='', shares=[], quality=0,
    monitor='0', monitor_connector='', fullscreen=False, capture_keyboard=True,
    clipboard=True, remember=False, keyboard_mode='fullscreen',
    fullscreen_shortcut='<Control><Alt>Return',
    remote_alt_tab=True, remote_super=True, remote_alt_f4=True,
    keyboard_shortcuts=[], auto_reconnect=True,
    profiles=[], active_profile='', appearance='dark', check_updates=True, update_prereleases=True)
PROFILE_KEYS = tuple(k for k in DEFAULT if k not in (
    'profiles', 'active_profile', 'appearance', 'check_updates', 'update_prereleases'))


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


def normalize_settings(data):
    cfg = copy.deepcopy(DEFAULT)
    if isinstance(data, dict):
        cfg.update({k: v for k, v in data.items() if k in PROFILE_KEYS})
    for key in ('server', 'user', 'monitor', 'monitor_connector'):
        cfg[key] = str(cfg[key]) if isinstance(cfg[key], (str, int)) else DEFAULT[key]
    for key in ('fullscreen', 'capture_keyboard', 'clipboard', 'remember',
                'remote_alt_tab', 'remote_super', 'remote_alt_f4', 'auto_reconnect'):
        cfg[key] = cfg[key] if isinstance(cfg[key], bool) else DEFAULT[key]
    if not isinstance(data, dict) or 'keyboard_mode' not in data:
        cfg['keyboard_mode'] = 'fullscreen' if cfg['capture_keyboard'] else 'local'
    if cfg['keyboard_mode'] not in ('fullscreen', 'always', 'local'):
        cfg['keyboard_mode'] = 'fullscreen'
    cfg['capture_keyboard'] = cfg['keyboard_mode'] != 'local'
    shortcut = cfg['fullscreen_shortcut']
    if not isinstance(shortcut, str) or not shortcut or len(shortcut) > 128:
        cfg['fullscreen_shortcut'] = DEFAULT['fullscreen_shortcut']
    cfg['keyboard_shortcuts'] = [dict(accelerator=rule['accelerator'], remote=rule['remote'])
        for rule in cfg['keyboard_shortcuts'] if isinstance(rule, dict)
        and isinstance(rule.get('accelerator'), str) and 0 < len(rule['accelerator']) <= 128
        and isinstance(rule.get('remote'), bool)][:128] \
        if isinstance(cfg['keyboard_shortcuts'], list) else []
    try:
        cfg['quality'] = max(0, min(2, int(cfg['quality'])))
    except (ValueError, TypeError):
        cfg['quality'] = 0
    cfg['shares'] = [dict(name=s['name'], path=s['path']) for s in cfg.get('shares', [])
                     if isinstance(s, dict) and isinstance(s.get('name'), str)
                     and isinstance(s.get('path'), str)] \
        if isinstance(cfg.get('shares'), list) else []
    return cfg


def load_cfg():
    data = {}
    try:
        data = json.loads(CFG_FILE.read_text())
    except (OSError, ValueError):
        pass
    cfg = normalize_settings(data)
    if isinstance(data, dict):
        appearance = data.get('appearance', 'dark')
        cfg['appearance'] = appearance if appearance in ('dark', 'light', 'system') else 'dark'
        for key in ('check_updates', 'update_prereleases'):
            cfg[key] = data[key] if isinstance(data.get(key), bool) else DEFAULT[key]
        seen = set()
        for profile in data.get('profiles', []) if isinstance(data.get('profiles'), list) else []:
            if not isinstance(profile, dict) or not isinstance(profile.get('id'), str) \
                    or not profile['id'] or profile['id'] in seen:
                continue
            settings = normalize_settings(profile)
            cfg['profiles'].append(dict(id=profile['id'],
                name=profile.get('name') if isinstance(profile.get('name'), str) else 'Conexão',
                **{k: settings[k] for k in PROFILE_KEYS}))
            seen.add(profile['id'])
        active = data.get('active_profile')
        cfg['active_profile'] = active if isinstance(active, str) and active in seen else ''
    if not cfg['profiles'] and (cfg['server'] or cfg['user']):
        store_profile(cfg, cfg['server'] or 'Minha conexão')
    return cfg


def save_cfg(cfg):
    # Explicit allowlist: credentials never enter the JSON, even nested in profiles.
    data = {k: copy.deepcopy(cfg.get(k, v)) for k, v in DEFAULT.items()}
    data['keyboard_shortcuts'] = normalize_settings(data)['keyboard_shortcuts']
    data['profiles'] = [{k: copy.deepcopy(p[k]) for k in ('id', 'name', *PROFILE_KEYS)
                         if k in p} for p in data['profiles']]
    for profile in data['profiles']:
        profile['keyboard_shortcuts'] = normalize_settings(profile)['keyboard_shortcuts']
    atomic_json(CFG_FILE, data)


def store_profile(cfg, name):
    profile = next((p for p in cfg['profiles'] if p['id'] == cfg['active_profile']), None)
    if profile is None:
        profile = dict(id=uuid.uuid4().hex)
        cfg['profiles'].append(profile)
        cfg['active_profile'] = profile['id']
    profile.update({k: copy.deepcopy(cfg[k]) for k in PROFILE_KEYS})
    profile['name'] = name.strip() or cfg['server'] or 'Conexão'
    return profile


def select_profile(cfg, profile_id):
    profile = next(p for p in cfg['profiles'] if p['id'] == profile_id)
    cfg.update({k: copy.deepcopy(profile[k]) for k in PROFILE_KEYS})
    cfg['active_profile'] = profile_id


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
           '-auto-reconnect',
           '/bpp:24' if cfg['quality'] == 2 else '/bpp:32',
           '+grab-keyboard' if cfg.get('keyboard_mode', 'fullscreen') != 'local'
                and cfg['capture_keyboard'] else '-grab-keyboard',
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
