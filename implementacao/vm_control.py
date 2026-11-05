"""Discover registered machines on this PC and configured remote Docker hosts."""
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
REMOTE_DOCKER_SCHEMES = frozenset(('ssh', 'tcp', 'http', 'https'))
# Grace period before Docker/Podman force-stop. Windows guests often ignore SIGTERM;
# a long wait makes the UI look stuck. Keep short; docker still SIGKILLs after this.
CONTAINER_STOP_TIMEOUT = 30
POWER_TIMEOUT = 60


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
    endpoint: str = ''
    context: str = ''

    @property
    def label(self):
        base = f'{self.name} · {BACKENDS[self.backend][0]}'
        if self.context:
            return f'{base} · {self.context}'
        if self.endpoint:
            return f'{base} · remoto'
        return base

    @property
    def binding(self):
        return self.backend, self.identifier, self.endpoint


def valid_identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 512 and not value.startswith('-') \
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)


def valid_endpoint(value):
    """Accept only explicit docker host URLs from configured contexts."""
    if not isinstance(value, str) or not value or len(value) > 512:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    try:
        url = urlsplit(value)
        path = unquote(url.path)
        netloc = unquote(url.netloc)
    except ValueError:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in path + netloc):
        return False
    if url.scheme in REMOTE_DOCKER_SCHEMES and url.netloc and not url.fragment:
        return True
    if url.scheme == 'unix' and not url.netloc and path.startswith('/') \
            and not url.query and not url.fragment:
        return True
    return False


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


def docker_config_dir():
    return Path(os.environ.get('DOCKER_CONFIG') or Path.home() / '.docker')


def docker_context_host(context, config=None):
    """Return the Host URL for a named context, or None for the engine default."""
    if not isinstance(context, str) or not context or context == 'default':
        return None
    config = config or docker_config_dir()
    digest = hashlib.sha256(context.encode()).hexdigest()
    metadata = read_docker_json(config / 'contexts/meta' / digest / 'meta.json')
    endpoints = metadata.get('Endpoints', {})
    docker = endpoints.get('docker', {}) if isinstance(endpoints, dict) else {}
    host = docker.get('Host') if isinstance(docker, dict) else None
    return host if isinstance(host, str) else None


def configured_docker_socket():
    """Honor the selected local unix context; remote contexts are handled separately."""
    config = docker_config_dir()
    context = os.environ.get('DOCKER_CONTEXT')
    host = os.environ.get('DOCKER_HOST')
    if not context and not host:
        context = read_docker_json(config / 'config.json').get('currentContext')
    if context and context != 'default':
        host = docker_context_host(context, config)
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


def list_docker_contexts():
    """Local unix sockets and configured remote Docker contexts (ssh/tcp/http)."""
    config = docker_config_dir()
    current = os.environ.get('DOCKER_CONTEXT') or read_docker_json(config / 'config.json').get('currentContext')
    env_host = os.environ.get('DOCKER_HOST')
    found = []
    seen = set()

    def add(name, host):
        if host is None:
            key = ('local', name or 'default')
            if key not in seen:
                seen.add(key)
                found.append(dict(name=name or 'default', host='', remote=False))
            return
        if not valid_endpoint(host):
            return
        try:
            url = urlsplit(host)
        except ValueError:
            return
        remote = url.scheme in REMOTE_DOCKER_SCHEMES
        if not remote and url.scheme == 'unix':
            # Local unix contexts still go through socket candidates / backends.
            return
        key = ('remote', host)
        if key in seen:
            return
        seen.add(key)
        found.append(dict(name=name or host, host=host, remote=True))

    if isinstance(env_host, str) and env_host:
        add(str(current) if isinstance(current, str) and current else 'DOCKER_HOST', env_host)
    meta_root = config / 'contexts/meta'
    try:
        entries = sorted(meta_root.iterdir()) if meta_root.is_dir() else []
    except OSError:
        entries = []
    for entry in entries:
        metadata = read_docker_json(entry / 'meta.json')
        name = metadata.get('Name') or metadata.get('name')
        if not isinstance(name, str) or not name:
            continue
        add(name, docker_context_host(name, config))
    if isinstance(current, str) and current and current != 'default':
        add(current, docker_context_host(current, config))
    return found


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


def command(backend, arguments, *, elevated=False, endpoint=''):
    if backend not in BACKENDS:
        raise VMError('Gerenciador de máquinas não reconhecido.')
    _label, tool, options = BACKENDS[backend]
    binary = find_tool(tool)
    if not binary:
        raise VMError(f'{tool} não está instalado neste computador.')
    if backend.startswith('docker'):
        if endpoint:
            if not valid_endpoint(endpoint):
                raise VMError('Endpoint Docker remoto inválido.')
            options = ('--host', endpoint)
        else:
            options, _status, _path = docker_host_args(backend)
    elif endpoint:
        raise VMError('Endpoint remoto só é suportado para Docker.')
    result = [binary, *options, *arguments]
    if elevated:
        if backend not in ELEVATABLE or endpoint:
            raise VMError('Este gerenciador deve ser usado com a conta atual.')
        pkexec = find_tool('pkexec')
        if not pkexec:
            raise VMError('A autorização gráfica requer pkexec neste computador.')
        result.insert(0, pkexec)
    return result


def run(backend, arguments, *, elevated=False, timeout=15, endpoint=''):
    # Explicit endpoint only; DOCKER_HOST/CONTEXT cannot redirect a power action.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('DOCKER_', 'CONTAINER_'))}
    env.update(LC_ALL='C', LANG='C')
    try:
        result = subprocess.run(
            command(backend, arguments, elevated=elevated, endpoint=endpoint),
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


def discover_docker(backend, *, elevated=False, endpoint='', context=''):
    template = '{"id":{{json .ID}},"name":{{json .Names}},"state":{{json .State}}}'
    try:
        output = run(backend, ['ps', '--all', '--no-trunc', '--format', template],
                     elevated=elevated, endpoint=endpoint)
        rows = parse_docker_rows(output)
    except (VMError, ValueError, TypeError, json.JSONDecodeError) as first:
        if isinstance(first, VMError) and (first.permission or daemon_unavailable(str(first))):
            raise
        # Older engines may lack the json template helper.
        output = run(backend,
            ['ps', '--all', '--no-trunc', '--format', '{{.ID}}\t{{.Names}}\t{{.Status}}'],
            elevated=elevated, endpoint=endpoint)
        try:
            rows = parse_docker_rows(output)
        except (ValueError, TypeError) as exc:
            raise VMError('Não foi possível interpretar a lista do Docker.') from exc
        if not rows and isinstance(first, VMError):
            raise first
    return [Machine(backend, identifier, name, state, endpoint=endpoint, context=context)
            for identifier, name, state in rows
            if valid_identifier(identifier) and valid_identifier(name)]


def discover_backend(backend, *, elevated=False, endpoint='', context=''):
    if backend.startswith('docker') or backend == 'podman':
        if backend.startswith('docker'):
            return discover_docker(backend, elevated=elevated, endpoint=endpoint, context=context)
        template = '{"id":{{json .ID}},"name":{{json .Names}},"state":{{json .State}}}'
        rows = [json.loads(line) for line in run(backend,
            ['ps', '--all', '--no-trunc', '--format', template], endpoint=endpoint).splitlines()
            if line.strip()]
        machines = [Machine(backend, row['id'],
            ', '.join(row['name']) if isinstance(row['name'], list) else row['name'], row['state'],
            endpoint=endpoint, context=context)
            for row in rows]
        return [machine for machine in machines if valid_identifier(machine.identifier)
                and valid_identifier(machine.name) and isinstance(machine.state, str)]
    if endpoint:
        raise VMError('Endpoint remoto só é suportado para Docker.')
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
    seen = set()

    def absorb(found):
        for machine in found:
            key = machine.binding
            if key in seen:
                continue
            seen.add(key)
            machines.append(machine)

    for backend, (label, tool, _options) in BACKENDS.items():
        if not find_tool(tool):
            continue
        if backend.startswith('docker'):
            _host, status, path = docker_host_args(backend)
            if backend == 'docker-user' and status == 'missing':
                notices.append(f'{label}: nenhum socket local do usuário encontrado.')
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
            absorb(found)
            queried.append(backend)
            if not found:
                notices.append(f'{label}: nenhuma máquina registrada neste computador.')
        except (VMError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            if isinstance(exc, VMError) and exc.permission and backend in ELEVATABLE:
                restricted.append(backend)
                notices.append(f'{label}: sem permissão. O AJR pedirá autorização do sistema.')
            elif isinstance(exc, VMError) and daemon_unavailable(str(exc)):
                notices.append(
                    f'{label}: serviço parece instalado, mas não respondeu ({exc}). '
                    f'Confira se o daemon está ativo.')
            else:
                notices.append(f'{label}: {exc}')

    if find_tool('docker'):
        for context in list_docker_contexts():
            if not context['remote']:
                continue
            available = True
            label = f"Docker remoto ({context['name']})"
            try:
                found = discover_docker('docker', endpoint=context['host'], context=context['name'])
                absorb(found)
                queried.append('docker:' + context['host'])
                if not found:
                    notices.append(f'{label}: nenhum contêiner registrado nesse host.')
            except (VMError, ValueError, TypeError, json.JSONDecodeError) as exc:
                if isinstance(exc, VMError) and exc.permission:
                    notices.append(f'{label}: sem permissão ({exc}).')
                elif isinstance(exc, VMError) and daemon_unavailable(str(exc)):
                    notices.append(f'{label}: host não respondeu ({exc}).')
                else:
                    notices.append(f'{label}: {exc}')

    if not available:
        notices.append(
            'Nenhum gerenciador compatível encontrado. '
            'Instale Docker, Podman, libvirt ou VirtualBox no PC que hospeda a VM, '
            'ou configure um contexto Docker remoto (ssh/tcp) neste computador.')
    elif not machines and not restricted and not queried:
        notices.append(
            'Nenhuma máquina acessível. A busca cobre Docker/Podman/libvirt/VirtualBox '
            'neste PC e contextos Docker remotos já configurados.')
    return sorted(machines, key=lambda machine: (
        machine.name.casefold(), machine.backend, machine.endpoint)), notices, restricted


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


GIB = 1024 ** 3
MIB = 1024 ** 2
KIB = 1024
SIZE_UNITS = {
    'b': 1, 'k': KIB, 'kb': KIB, 'ki': KIB, 'kib': KIB,
    'm': MIB, 'mb': MIB, 'mi': MIB, 'mib': MIB,
    'g': GIB, 'gb': GIB, 'gi': GIB, 'gib': GIB,
    't': 1024 ** 4, 'tb': 1024 ** 4, 'ti': 1024 ** 4, 'tib': 1024 ** 4,
}


@dataclass(frozen=True)
class MemoryStatus:
    used_bytes: int
    limit_bytes: int
    running: bool


def bound_machine(cfg):
    """Rebuild the linked Machine from profile fields, or None if unbound/invalid."""
    backend = cfg.get('vm_backend', '')
    identifier = cfg.get('vm_id', '')
    name = cfg.get('vm_name', '')
    endpoint = cfg.get('vm_host', '') or ''
    if not isinstance(backend, str) or backend not in BACKENDS or not valid_identifier(identifier):
        return None
    if endpoint and not valid_endpoint(endpoint):
        return None
    if not isinstance(name, str) or not valid_identifier(name):
        name = identifier
    return Machine(backend, identifier, name, endpoint=endpoint)


def parse_size(text):
    if not isinstance(text, str):
        raise ValueError('tamanho inválido')
    match = re.fullmatch(r'([0-9]*\.?[0-9]+)\s*([A-Za-z]+)?', text.strip().replace(',', '.'))
    if not match:
        raise ValueError('tamanho inválido')
    amount = float(match.group(1))
    unit = (match.group(2) or 'b').casefold()
    if unit not in SIZE_UNITS or amount < 0 or amount > 1e9:
        raise ValueError('tamanho inválido')
    return int(amount * SIZE_UNITS[unit])


def _docker_memory_status(machine, *, elevated=False):
    endpoint = machine.endpoint or ''
    limit_text = run(machine.backend,
        ['inspect', '--format', '{{.HostConfig.Memory}}', machine.identifier],
        elevated=elevated, endpoint=endpoint).strip()
    running_text = run(machine.backend,
        ['inspect', '--format', '{{.State.Running}}', machine.identifier],
        elevated=elevated, endpoint=endpoint).strip().casefold()
    try:
        limit_bytes = int(limit_text or 0)
    except ValueError as exc:
        raise VMError('Não foi possível ler o limite de RAM do contêiner.') from exc
    if limit_bytes < 0:
        limit_bytes = 0
    running = running_text in ('true', '1')
    used_bytes = 0
    if running:
        usage = run(machine.backend,
            ['stats', '--no-stream', '--format', '{{.MemUsage}}', machine.identifier],
            elevated=elevated, endpoint=endpoint).strip()
        left = usage.split('/', 1)[0].strip()
        try:
            used_bytes = parse_size(left)
        except ValueError as exc:
            raise VMError('Não foi possível interpretar o uso de RAM do contêiner.') from exc
    return MemoryStatus(used_bytes, limit_bytes, running)


def _libvirt_memory_status(machine, *, elevated=False):
    info = run(machine.backend, ['dominfo', '--domain', machine.identifier], elevated=elevated)
    max_kib = used_kib = None
    state = ''
    for line in info.splitlines():
        key, _, value = line.partition(':')
        key, value = key.strip().casefold(), value.strip()
        if key == 'max memory':
            max_kib = int(value.split()[0])
        elif key == 'used memory':
            used_kib = int(value.split()[0])
        elif key == 'state':
            state = value.casefold()
    if max_kib is None or used_kib is None:
        raise VMError('Não foi possível ler a memória da máquina libvirt.')
    return MemoryStatus(used_kib * KIB, max_kib * KIB, 'running' in state)


def _virtualbox_memory_status(machine, *, elevated=False):
    output = run(machine.backend, ['showvminfo', machine.identifier, '--machinereadable'],
                 elevated=elevated)
    memory_mb = None
    running = False
    for line in output.splitlines():
        if line.startswith('memory='):
            memory_mb = int(line.split('=', 1)[1].strip().strip('"'))
        elif line.startswith('VMState='):
            running = line.split('=', 1)[1].strip().strip('"').casefold() == 'running'
    if memory_mb is None or memory_mb < 1:
        raise VMError('Não foi possível ler a memória da máquina VirtualBox.')
    limit_bytes = memory_mb * MIB
    # VirtualBox guest usage metrics are optional; report the configured ceiling as used when stopped.
    used_bytes = limit_bytes if running else 0
    return MemoryStatus(used_bytes, limit_bytes, running)


def memory_status(machine, *, elevated=False):
    """Read hypervisor-configured RAM limit and current usage for a linked machine."""
    if not valid_identifier(machine.identifier):
        raise VMError('Máquina inválida.')
    if machine.backend.startswith('docker') or machine.backend == 'podman':
        return _docker_memory_status(machine, elevated=elevated)
    if machine.backend.startswith('libvirt'):
        return _libvirt_memory_status(machine, elevated=elevated)
    if machine.backend == 'virtualbox':
        return _virtualbox_memory_status(machine, elevated=elevated)
    raise VMError('Gerenciador de máquinas não reconhecido.')


def set_memory_limit(machine, limit_gib, *, elevated=False):
    """Apply a hard RAM ceiling on the hypervisor for the linked machine."""
    try:
        limit_gib = float(limit_gib)
    except (TypeError, ValueError) as exc:
        raise VMError('Limite de RAM inválido.') from exc
    if not (0.25 <= limit_gib <= 65536):
        raise VMError('Informe um limite de RAM entre 0,25 e 65536 GiB.')
    if not valid_identifier(machine.identifier):
        raise VMError('Máquina inválida.')
    endpoint = machine.endpoint or ''
    if endpoint and not valid_endpoint(endpoint):
        raise VMError('Endpoint Docker remoto inválido.')
    memory_mib = max(256, int(round(limit_gib * 1024)))
    if machine.backend.startswith('docker') or machine.backend == 'podman':
        mem = f'{memory_mib}m'
        return run(machine.backend,
            ['update', '--memory', mem, '--memory-swap', mem, machine.identifier],
            elevated=elevated, endpoint=endpoint, timeout=60)
    if machine.backend.startswith('libvirt'):
        kib = memory_mib * KIB
        # Raise max first, then current allocation; try live when the guest is up.
        run(machine.backend, ['setmaxmem', '--domain', machine.identifier, str(kib), '--config'],
            elevated=elevated, timeout=60)
        run(machine.backend, ['setmem', '--domain', machine.identifier, str(kib), '--config'],
            elevated=elevated, timeout=60)
        try:
            run(machine.backend, ['setmaxmem', '--domain', machine.identifier, str(kib), '--live'],
                elevated=elevated, timeout=60)
            run(machine.backend, ['setmem', '--domain', machine.identifier, str(kib), '--live'],
                elevated=elevated, timeout=60)
        except VMError:
            pass
        return ''
    if machine.backend == 'virtualbox':
        status = _virtualbox_memory_status(machine, elevated=elevated)
        if status.running:
            raise VMError('Desligue a VM VirtualBox para aplicar o limite de RAM.')
        return run(machine.backend,
            ['modifyvm', machine.identifier, '--memory', str(memory_mib)],
            elevated=elevated, timeout=60)
    raise VMError('Gerenciador de máquinas não reconhecido.')


def power(machine, action, *, elevated=False, memory_gib=None):
    if action not in ('start', 'stop') or not valid_identifier(machine.identifier):
        raise VMError('Máquina ou ação inválida.')
    endpoint = machine.endpoint or ''
    if endpoint and not valid_endpoint(endpoint):
        raise VMError('Endpoint Docker remoto inválido.')
    if action == 'start' and memory_gib is not None:
        set_memory_limit(machine, memory_gib, elevated=elevated)
    if machine.backend.startswith('docker') or machine.backend == 'podman':
        arguments = ['start', machine.identifier] if action == 'start' else \
                    ['stop', '--timeout', str(CONTAINER_STOP_TIMEOUT), machine.identifier]
    elif machine.backend.startswith('libvirt'):
        arguments = ['start' if action == 'start' else 'shutdown', '--domain', machine.identifier]
    elif machine.backend == 'virtualbox':
        arguments = ['startvm', machine.identifier, '--type', 'headless'] if action == 'start' else \
                    ['controlvm', machine.identifier, 'acpipowerbutton']
    else:
        raise VMError('Gerenciador de máquinas não reconhecido.')
    # Container stop waits the grace period; ACPI backends return quickly.
    timeout = POWER_TIMEOUT if action == 'stop' else 180
    return run(machine.backend, arguments, elevated=elevated, timeout=timeout, endpoint=endpoint)
