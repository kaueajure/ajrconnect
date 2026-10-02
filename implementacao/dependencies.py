"""Install missing runtime packages for the validated Zorin target only."""
import ctypes
import os
import platform
import re
import shutil
import subprocess
from check_compatibility import read_os_release, supported_os

PACKAGES = ('python3', 'python3-gi', 'gir1.2-gtk-4.0', 'gir1.2-adw-1',
            'gnome-shell', 'gnome-keyring', 'xwayland', 'x11-xserver-utils',
            'libsecret-tools', 'libx11-6', 'libxrender1', 'libxrandr2',
            'libxinerama1', 'libxcursor1', 'libxfixes3', 'libxext6')
RDP_PACKAGES = ('libfreerdp2-2t64', 'libfreerdp-client2-2t64', 'libwinpr2-2t64')


class DependencyError(RuntimeError):
    pass


def run(command, capture=True):
    try:
        result = subprocess.run(command, capture_output=capture, text=True,
                                env=dict(os.environ, LC_ALL='C'))
    except OSError as error:
        raise DependencyError(str(error)) from error
    if result.returncode:
        detail = (result.stderr or result.stdout or '').strip() if capture else ''
        raise DependencyError('Falha ao executar ' + command[0] +
                              (': ' + detail if detail else '.'))
    return result.stdout or ''


def validate_target():
    if os.geteuid() == 0:
        raise DependencyError('Execute na sessão do usuário, sem sudo.')
    if platform.system() != 'Linux' or platform.machine() != 'x86_64' or not supported_os(read_os_release()):
        raise DependencyError('Esta versão requer Zorin OS 18.1 x86_64.')
    if (os.environ.get('XDG_SESSION_TYPE') != 'wayland'
            or not os.environ.get('DISPLAY') or not os.environ.get('WAYLAND_DISPLAY')
            or 'GNOME' not in os.environ.get('XDG_CURRENT_DESKTOP', '').split(':')):
        raise DependencyError('Execute dentro da sessão GNOME Wayland com XWayland disponível.')
    if not re.search(r'^GNOME Shell 46(?:\.|$)', run(['gnome-shell', '--version'])):
        raise DependencyError('Esta versão requer GNOME Shell 46.')
    for tool in ('apt-get', 'apt-cache', 'dpkg-query'):
        if not shutil.which(tool):
            raise DependencyError('Ferramenta ausente: ' + tool)


def compatible_rdp_version(version):
    # Permit distribution security revisions; do not pin an obsolete build suffix.
    return re.match(r'^2\.11\.5(?:$|[+~\-])', version.split(':', 1)[-1]) is not None


def installed_version(package):
    result = subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}\t${Version}', package],
                            capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.startswith('installed\t'):
        return result.stdout.split('\t', 1)[1].strip()
    return None


def candidate_version(package):
    match = re.search(r'^\s*Candidate:\s*(\S+)', run(['apt-cache', 'policy', package]), re.MULTILINE)
    return match.group(1) if match else ''


def validate_existing_rdp(installed):
    for package in RDP_PACKAGES:
        version = installed[package]
        if version and not compatible_rdp_version(version):
            raise DependencyError(package + ' está na versão ' + version +
                                  '; esperado 2.11.5. Não será feito downgrade automático.')
    # Catch manually installed libraries that do not appear in the package database.
    for library, symbol in (('libfreerdp2.so.2', 'freerdp_get_version_string'),
                            ('libwinpr2.so.2', 'winpr_get_version_string')):
        try:
            loaded = ctypes.CDLL(library)
            function = getattr(loaded, symbol)
            function.restype = ctypes.c_char_p
            version = function().decode()
        except OSError:
            continue  # Missing libraries/dependencies are handled by APT.
        if version != '2.11.5':
            raise DependencyError(library + ': versão incompatível ' + version + '.')


def ensure_dependencies():
    """Return success only after required packages exist; never run the app as root."""
    try:
        validate_target()
        installed = {package: installed_version(package) for package in PACKAGES + RDP_PACKAGES}
        validate_existing_rdp(installed)
        missing = [package for package, version in installed.items() if version is None]
        if not missing:
            print('Dependências já instaladas.')
            return True
        if not shutil.which('sudo'):
            raise DependencyError('sudo não está disponível para instalar as dependências.')
        print('Dependências ausentes: ' + ', '.join(missing), flush=True)
        print('Será solicitada a senha de administrador apenas para instalar esses pacotes.', flush=True)
        run(['sudo', '-v'], capture=False)
        run(['sudo', 'apt-get', 'update'], capture=False)
        requests = []
        for package in missing:
            if package in RDP_PACKAGES:
                candidate = candidate_version(package)
                if not compatible_rdp_version(candidate):
                    raise DependencyError('O repositório não oferece ' + package +
                                          ' na versão 2.11.5. Instalação interrompida.')
                requests.append(package + '=' + candidate)
            else:
                requests.append(package)
        options = ['--no-remove', '--no-install-recommends']
        run(['apt-get', '--simulate', *options, 'install', *requests])
        run(['sudo', 'apt-get', '--yes', *options, 'install', *requests], capture=False)
        for package in PACKAGES + RDP_PACKAGES:
            version = installed_version(package)
            if not version or (package in RDP_PACKAGES and not compatible_rdp_version(version)):
                raise DependencyError('Dependência não ficou disponível: ' + package)
        print('Dependências instaladas. Continuando com o usuário atual.')
        return True
    except (DependencyError, OSError, ValueError, AttributeError) as error:
        print('Instalação interrompida: ' + str(error), flush=True)
        return False
