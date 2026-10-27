"""Discover registered local machines; execute only explicit power actions."""
from dataclasses import dataclass
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
from urllib.parse import unquote, urlsplit

BACKENDS = {
    'docker': ('Docker', 'docker', ()),
    'docker-user': ('Docker do usuário', 'docker', ()),
    'podman': ('Podman do usuário', 'podman', ('--remote=false',)),
    'libvirt': ('KVM/libvirt do sistema', 'virsh', ('--connect', 'qemu:///system')),
    'libvirt-user': ('KVM/libvirt do usuário', 'virsh', ('--connect', 'qemu:///session')),
    'virtualbox': ('VirtualBox', 'VBoxManage', ()),
}
ELEVATABLE = frozenset(('docker', 'libvirt'))
PERMISSION_MARKERS = (
    'permission denied', 'access denied', 'not authorized', 'authentication required',
    'authorization requires authentication', 'operação não permitida', 'permissão negada',
    'acesso negado',
)
DAEMON_MARKERS = (
    'cannot connect to the docker daemon', 'is the docker daemon running',
    'no such file or directory', 'connection refused', 'error connecting',
)
TOOL_PATHS = ('/usr/bin', '/usr/local/bin', '/snap/bin', '/bin', '/usr/sbin', '/sbin')


class VMError(RuntimeError):
    def __init__(self, message, *, permission=False):
        super().__init__(message)
        self.permission = permission


@dataclass(frozen=True)
class Machine:
    backend: str
    identifier: str
    name: str
    state: str = ''

    @property
    def label(self):
        return f'{self.name} · {BACKENDS[self.backend][0]}'


def valid_identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 512 and not value.startswith('-') \
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)


def find_tool(tool):
    found = shutil.which(tool)
    if found:
        return found
    for directory in TOOL_PATHS:
        candidate = Path(directory) / tool
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def permission_denied(detail):
    text = detail.casefold()
    return any(marker in text for marker in PERMISSION_MARKERS)


def daemon_unavailable(detail):
    text = detail.casefold()
    # Prefer permission classification when both markers appear (common Docker ACL error).
    if permission_denied(detail):
        return False
    return any(marker in text for marker in DAEMON_MARKERS)


def is_socket(path):
    try:
        return stat.S_ISSOCK(path.stat().st_mode)
    except OSError:
        return False


def read_docker_json(path):
    try:
        # Read only client metadata; never return credentials in diagnostics.
        with path.open('rb') as stream:
            value = json.loads(stream.read(1024 * 1024))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def configured_docker_socket():
    """Honor the selected local context, without connecting to remote daemons."""
    config = Path(os.environ.get('DOCKER_CONFIG') or Path.home() / '.docker')
    context = os.environ.get('DOCKER_CONTEXT')
    host = os.environ.get('DOCKER_HOST')
    if not context and not host:
        context = read_docker_json(config / 'config.json').get('currentContext')
    if context and context != 'default':
        if not isinstance(context, str):
            return None
        digest = hashlib.sha256(context.encode()).hexdigest()
        metadata = read_docker_json(config / 'contexts/meta' / digest / 'meta.json')
        endpoints = metadata.get('Endpoints', {})
        docker = endpoints.get('docker', {}) if isinstance(endpoints, dict) else {}
        host = docker.get('Host') if isinstance(docker, dict) else None
    elif context == 'default':
        host = None
    if not isinstance(host, str):
        return None
    try:
        url = urlsplit(host)
        path = unquote(url.path)
    except ValueError:
        return None
    if url.scheme != 'unix' or url.netloc or url.query or url.fragment \
            or not path.startswith('/') or any(ord(c) < 32 for c in path):
        return None
    return Path(path)


def docker_socket_candidates(backend):
    home = Path.home()
    uid = os.getuid()
    system = (Path('/var/run/docker.sock'), Path('/run/docker.sock'))
    user = (
        Path(f'/run/user/{uid}/docker.sock'),
        home / '.docker' / 'desktop' / 'docker.sock',
        home / '.docker' / 'run' / 'docker.sock',
    )
    runtime = os.environ.get('XDG_RUNTIME_DIR', '')
    if runtime and Path(runtime).is_absolute():
        user = (Path(runtime) / 'docker.sock',) + user
    # Keep backends disjoint: system docker must not also appear as "docker-user".
    ordered = user if backend == 'docker-user' else system + (
        home / '.docker' / 'desktop' / 'docker.sock',
        home / '.docker' / 'run' / 'docker.sock',
    )
    configured = configured_docker_socket()
    if configured is not None:
        user_roots = (home, Path(f'/run/user/{uid}'))
        if runtime and Path(runtime).is_absolute():
            user_roots += (Path(runtime),)
        user_socket = any(configured.is_relative_to(root) for root in user_roots)
        if (backend == 'docker-user') == user_socket:
            ordered = (configured,) + ordered
    seen, result = set(), []
    for path in ordered:
        key = os.path.realpath(path)
        if key in seen:
            continue
        seen.add(key)
        if is_socket(path):
            result.append(path)
    return result


def resolve_docker_socket(backend):
    candidates = docker_socket_candidates(backend)
    if not candidates:
        return None, 'missing'
    for path in candidates:
        if os.access(path, os.R_OK | os.W_OK):
            return path, 'ok'
    return candidates[0], 'denied'


def docker_host_args(backend):
    path, status = resolve_docker_socket(backend)
    if path is None:
        # Keep a stable default for elevated retries / clearer daemon errors.
        fallback = '/run/user/%s/docker.sock' % os.getuid() if backend == 'docker-user' \
            else '/var/run/docker.sock'
        return ('--host', 'unix://' + fallback), 'missing', Path(fallback)
    return ('--host', 'unix://' + str(path)), status, path


def command(backend, arguments, *, elevated=False):
    if backend not in BACKENDS:
        raise VMError('Gerenciador de máquinas não reconhecido.')
    _label, tool, options = BACKENDS[backend]
    binary = find_tool(tool)
    if not binary:
        raise VMError(f'{tool} não está instalado neste computador.')
    if backend.startswith('docker'):
        options, _status, _path = docker_host_args(backend)
    result = [binary, *options, *arguments]
    if elevated:
        if backend not in ELEVATABLE:
            raise VMError('Este gerenciador deve ser usado com a conta atual.')
        pkexec = find_tool('pkexec')
        if not pkexec:
            raise VMError('A autorização gráfica requer pkexec neste computador.')
        result.insert(0, pkexec)
    return result


def run(backend, arguments, *, elevated=False, timeout=15):
    # Fixed local endpoints: DOCKER_HOST/CONTEXT cannot redirect a power action.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('DOCKER_', 'CONTAINER_'))}
    env.update(LC_ALL='C', LANG='C')
    try:
        result = subprocess.run(command(backend, arguments, elevated=elevated),
            stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise VMError('O gerenciador não respondeu a tempo. Atualize a busca para conferir o estado.') from exc
    except OSError as exc:
        raise VMError('Não foi possível executar o gerenciador: ' + str(exc)) from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or 'Falha sem detalhes.').strip()[:1200]
        if elevated and result.returncode in (126, 127):
            raise VMError('Autorização cancelada ou não concedida pelo sistema.')
        raise VMError(detail, permission=permission_denied(detail))
    return result.stdout


def normalize_docker_state(value):
    text = (value or '').strip().casefold()
    if text in ('running', 'created', 'exited', 'paused', 'restarting', 'dead', 'removing'):
        return text
    if text.startswith('up'):
        return 'running'
    if text.startswith('exited') or text.startswith('created'):
        return 'exited' if text.startswith('exited') else 'created'
    if 'paused' in text:
        return 'paused'
    return value.strip() if isinstance(value, str) else ''


def parse_docker_rows(output):
    machines = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('{'):
            row = json.loads(line)
            name = row.get('name') or row.get('Names') or ''
            if isinstance(name, list):
                name = ', '.join(name)
            machines.append((row.get('id') or row.get('ID'), name,
                             normalize_docker_state(row.get('state') or row.get('Status') or '')))
            continue
        parts = line.split('\t')
        if len(parts) >= 3:
            machines.append((parts[0], parts[1], normalize_docker_state(parts[2])))
    return machines


def discover_docker(backend, *, elevated=False):
    template = '{"id":{{json .ID}},"name":{{json .Names}},"state":{{json .State}}}'
    try:
        output = run(backend, ['ps', '--all', '--no-trunc', '--format', template], elevated=elevated)
        rows = parse_docker_rows(output)
    except (VMError, ValueError, TypeError, json.JSONDecodeError) as first:
        if isinstance(first, VMError) and (first.permission or daemon_unavailable(str(first))):
            raise
        # Older engines may lack the json template helper.
        output = run(backend,
            ['ps', '--all', '--no-trunc', '--format', '{{.ID}}\t{{.Names}}\t{{.Status}}'],
            elevated=elevated)
        try:
            rows = parse_docker_rows(output)
        except (ValueError, TypeError) as exc:
            raise VMError('Não foi possível interpretar a lista do Docker.') from exc
        if not rows and isinstance(first, VMError):
            raise first
    return [Machine(backend, identifier, name, state) for identifier, name, state in rows
            if valid_identifier(identifier) and valid_identifier(name)]


def discover_backend(backend, *, elevated=False):
    if backend.startswith('docker') or backend == 'podman':
        if backend.startswith('docker'):
            return discover_docker(backend, elevated=elevated)
        template = '{"id":{{json .ID}},"name":{{json .Names}},"state":{{json .State}}}'
        rows = [json.loads(line) for line in run(backend,
            ['ps', '--all', '--no-trunc', '--format', template]).splitlines() if line.strip()]
        machines = [Machine(backend, row['id'],
            ', '.join(row['name']) if isinstance(row['name'], list) else row['name'], row['state'])
            for row in rows]
        return [machine for machine in machines if valid_identifier(machine.identifier)
                and valid_identifier(machine.name) and isinstance(machine.state, str)]
    if backend.startswith('libvirt'):
        machines = []
        identifiers = run(backend, ['list', '--all', '--uuid'], elevated=elevated).splitlines()
        for identifier in identifiers:
            if not identifier.strip():
                continue
            identifier = identifier.strip()
            if not valid_identifier(identifier):
                continue
            name = run(backend, ['domname', '--domain', identifier], elevated=elevated).strip()
            state = run(backend, ['domstate', '--domain', identifier], elevated=elevated).strip()
            machines.append(Machine(backend, identifier, name, state))
        return [machine for machine in machines if valid_identifier(machine.identifier)
                and valid_identifier(machine.name) and isinstance(machine.state, str)]
    registered = run(backend, ['list', 'vms'])
    running = run(backend, ['list', 'runningvms'])
    active = set(re.findall(r'\{([0-9a-fA-F-]{36})\}', running))
    machines = []
    for line in registered.splitlines():
        match = re.fullmatch(r'"(.*)" \{([0-9a-fA-F-]{36})\}', line)
        if match:
            name, identifier = match.groups()
            machines.append(Machine(backend, identifier, name,
                                    'running' if identifier in active else 'stopped'))
    return [machine for machine in machines if valid_identifier(machine.identifier)
            and valid_identifier(machine.name) and isinstance(machine.state, str)]


def discover(elevated=()):
    machines, notices, restricted = [], [], []
    available = False
    queried = []
    for backend, (label, tool, _options) in BACKENDS.items():
        if not find_tool(tool):
            continue
        if backend.startswith('docker'):
            _host, status, path = docker_host_args(backend)
            if backend == 'docker-user' and status == 'missing':
                continue
            available = True
            if status == 'denied' and backend in ELEVATABLE and backend not in elevated:
                restricted.append(backend)
                notices.append(f'{label}: sem permissão em {path}. O AJR pedirá autorização do sistema.')
                continue
            if status == 'missing' and backend not in elevated:
                # Still attempt once — some installs expose the CLI before the sock path settles.
                pass
        else:
            available = True
        try:
            found = discover_backend(backend, elevated=backend in elevated)
            machines.extend(found)
            queried.append(backend)
            if not found:
                notices.append(f'{label}: nenhum contêiner ou máquina registrada neste computador.')
        except (VMError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            if isinstance(exc, VMError) and exc.permission and backend in ELEVATABLE:
                restricted.append(backend)
                notices.append(f'{label}: sem permissão. O AJR pedirá autorização do sistema.')
            elif isinstance(exc, VMError) and daemon_unavailable(str(exc)):
                notices.append(
                    f'{label}: Docker/VM parece instalado, mas o serviço local não respondeu '
                    f'({exc}). Confira se o daemon está ativo neste PC.')
            else:
                notices.append(f'{label}: {exc}')
    if not available:
        notices.append(
            'Nenhum gerenciador compatível encontrado neste computador. '
            'Instale Docker, Podman, libvirt ou VirtualBox no PC que hospeda a VM.')
    elif not machines and not restricted and not queried:
        notices.append(
            'Nenhuma máquina local acessível. Ligar/desligar só funciona no computador '
            'que hospeda o Docker/VM.')
    return sorted(machines, key=lambda machine: (machine.name.casefold(), machine.backend)), notices, restricted


def docker_group_active():
    try:
        return grp.getgrnam('docker').gr_gid in os.getgroups()
    except KeyError:
        return False


def current_username():
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return os.environ.get('USER') or os.environ.get('LOGNAME') or ''


def docker_group_configured():
    user = current_username()
    try:
        group = grp.getgrnam('docker')
    except KeyError:
        return False
    if docker_group_active() or user in group.gr_mem:
        return True
    try:
        return pwd.getpwnam(user).pw_gid == group.gr_gid
    except KeyError:
        return False


def ensure_docker_group():
    """Grant permanent docker socket access via polkit. Returns True if membership changed."""
    if docker_group_configured():
        return False
    user = current_username()
    if not user or user.startswith('-'):
        raise VMError('Não foi possível identificar o usuário atual para liberar o Docker.')
    usermod = find_tool('usermod')
    pkexec = find_tool('pkexec')
    if not usermod or not pkexec:
        raise VMError('Não foi possível configurar o acesso permanente ao Docker neste sistema.')
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('DOCKER_', 'CONTAINER_'))}
    env.update(LC_ALL='C', LANG='C')
    try:
        result = subprocess.run([pkexec, usermod, '-aG', 'docker', user],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise VMError('A configuração do acesso ao Docker excedeu o tempo limite.') from exc
    except OSError as exc:
        raise VMError('Não foi possível configurar o acesso ao Docker: ' + str(exc)) from exc
    if result.returncode in (126, 127):
        raise VMError('Autorização cancelada ou não concedida pelo sistema.')
    if result.returncode:
        detail = (result.stderr or result.stdout or 'Falha sem detalhes.').strip()[:1200]
        raise VMError(detail, permission=permission_denied(detail))
    return True


def power(machine, action, *, elevated=False):
    if action not in ('start', 'stop') or not valid_identifier(machine.identifier):
        raise VMError('Máquina ou ação inválida.')
    if machine.backend.startswith('docker') or machine.backend == 'podman':
        arguments = ['start', machine.identifier] if action == 'start' else \
                    ['stop', '--timeout', '120', machine.identifier]
    elif machine.backend.startswith('libvirt'):
        arguments = ['start' if action == 'start' else 'shutdown', '--domain', machine.identifier]
    elif machine.backend == 'virtualbox':
        arguments = ['startvm', machine.identifier, '--type', 'headless'] if action == 'start' else \
                    ['controlvm', machine.identifier, 'acpipowerbutton']
    else:
        raise VMError('Gerenciador de máquinas não reconhecido.')
    return run(machine.backend, arguments, elevated=elevated, timeout=180)
