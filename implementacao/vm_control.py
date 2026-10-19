"""Discover registered local machines; execute only explicit power actions."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

BACKENDS = {
    'docker': ('Docker', 'docker', ('--host', 'unix:///var/run/docker.sock')),
    'docker-user': ('Docker do usuário', 'docker',
                    ('--host', f'unix:///run/user/{os.getuid()}/docker.sock')),
    'podman': ('Podman do usuário', 'podman', ('--remote=false',)),
    'libvirt': ('KVM/libvirt do sistema', 'virsh', ('--connect', 'qemu:///system')),
    'libvirt-user': ('KVM/libvirt do usuário', 'virsh', ('--connect', 'qemu:///session')),
    'virtualbox': ('VirtualBox', 'VBoxManage', ()),
}
ELEVATABLE = frozenset(('docker', 'libvirt'))


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


def command(backend, arguments, *, elevated=False):
    if backend not in BACKENDS:
        raise VMError('Gerenciador de máquinas não reconhecido.')
    _label, tool, options = BACKENDS[backend]
    binary = shutil.which(tool)
    if not binary:
        raise VMError(f'{tool} não está instalado neste computador.')
    result = [binary, *options, *arguments]
    if elevated:
        if backend not in ELEVATABLE:
            raise VMError('Este gerenciador deve ser usado com a conta atual.')
        pkexec = shutil.which('pkexec')
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
        permission = any(word in detail.casefold() for word in
            ('permission denied', 'access denied', 'not authorized', 'authentication required',
             'authorization requires authentication'))
        if elevated and result.returncode in (126, 127):
            raise VMError('Autorização cancelada ou não concedida pelo sistema.')
        raise VMError(detail, permission=permission)
    return result.stdout


def discover_backend(backend, *, elevated=False):
    machines = []
    if backend.startswith('docker'):
        # Select only display metadata, never container commands/env/secrets.
        template = '{"id":{{json .ID}},"name":{{json .Names}},"state":{{json .State}}}'
        rows = [json.loads(line) for line in run(backend,
            ['ps', '--all', '--no-trunc', '--format', template], elevated=elevated).splitlines() if line.strip()]
        machines = [Machine(backend, row['id'], row['name'], row['state']) for row in rows]
    elif backend == 'podman':
        template = '{"id":{{json .ID}},"name":{{json .Names}},"state":{{json .State}}}'
        rows = [json.loads(line) for line in run(backend,
            ['ps', '--all', '--no-trunc', '--format', template]).splitlines() if line.strip()]
        machines = [Machine(backend, row['id'],
            ', '.join(row['name']) if isinstance(row['name'], list) else row['name'], row['state']) for row in rows]
    elif backend.startswith('libvirt'):
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
    else:
        registered = run(backend, ['list', 'vms'])
        running = run(backend, ['list', 'runningvms'])
        active = set(re.findall(r'\{([0-9a-fA-F-]{36})\}', running))
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
    for backend, (label, tool, _options) in BACKENDS.items():
        if not shutil.which(tool):
            continue
        if backend == 'docker-user' and not Path(f'/run/user/{os.getuid()}/docker.sock').exists():
            continue
        available = True
        try:
            machines.extend(discover_backend(backend, elevated=backend in elevated))
        except (VMError, ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, VMError) and exc.permission and backend in ELEVATABLE:
                restricted.append(backend)
                notices.append(f'{label}: autorize a consulta para listar as máquinas.')
            else:
                notices.append(f'{label}: {exc}')
    if not available:
        notices.append('Nenhum gerenciador compatível encontrado. Instale Docker, Podman, libvirt ou VirtualBox para controlar uma máquina local.')
    return sorted(machines, key=lambda machine: (machine.name.casefold(), machine.backend)), notices, restricted


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
