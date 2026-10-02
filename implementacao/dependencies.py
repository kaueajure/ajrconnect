"""Install runtime dependencies by capability, without a distribution whitelist."""
import ctypes
import os
import re
import shutil
import subprocess
import sys
from check_compatibility import GI_PROBE, LIBRARY_PROBE, run as probe

PACKAGES = ('python3', 'python3-gi', 'gir1.2-gtk-4.0', 'gir1.2-adw-1',
            'x11-xserver-utils',
            'libsecret-tools', 'libx11-6', 'libxrender1', 'libxrandr2',
            'libxinerama1', 'libxcursor1', 'libxfixes3', 'libxext6')
RDP_PACKAGES = ('libfreerdp2-2t64', 'libfreerdp-client2-2t64', 'libwinpr2-2t64')
RDP_CHOICES = {package: (package, package.removesuffix('t64')) for package in RDP_PACKAGES}


class DependencyError(RuntimeError):
    pass


def run(command, capture=True):
    try:
        result = subprocess.run(command, capture_output=capture, text=True,
                                env=dict(os.environ, LC_ALL='C'))
    except OSError as error:
        raise DependencyError(str(error)) from error
    detail = '\n'.join(part.strip() for part in (result.stdout, result.stderr) if part).strip() if capture else ''
    signature_failure = ('apt-get' in command and
                         any(marker in detail for marker in
                             ('NO_PUBKEY', 'EXPKEYSIG', 'BADSIG', 'not signed')))
    # APT may return zero while reusing stale indexes for a failing repository.
    if result.returncode or signature_failure:
        remedy = ''
        if signature_failure:
            remedy = ('\nO APT bloqueou um repositório por falha de assinatura/chave GPG. '
                      'Corrija a chave e a configuração desse repositório conforme o fornecedor, '
                      'ou desative somente essa fonte se não a utiliza. '
                      'Se as listas estiverem desatualizadas, execute sudo apt-get update '
                      'manualmente antes de tentar novamente. '
                      'Um aviso sobre i386 não indica a arquitetura deste computador.')
            if 'deb.anydesk.com' in detail:
                remedy += '\nAnyDesk: https://deb.anydesk.com/howto.html'
        elif 'apt-get' in command and 'install' in command:
            remedy = ('\nO instalador não atualiza as listas de pacotes. Se estiverem '
                      'desatualizadas, corrija eventuais falhas de repositório e '
                      'execute sudo apt-get update manualmente.')
        raise DependencyError('Falha ao executar ' + ' '.join(command) +
                              ' (código ' + str(result.returncode) + ')' +
                              (': ' + detail if detail else '.') + remedy)
    if capture and command[:2] == ['sudo', 'apt-get'] and result.stdout:
        print(result.stdout, end='', flush=True)
    if capture and command[:2] == ['sudo', 'apt-get'] and result.stderr:
        print(result.stderr, end='', file=sys.stderr, flush=True)
    return result.stdout or ''


def validate_target():
    if os.geteuid() == 0:
        raise DependencyError('Execute na sessão do usuário, sem sudo.')


def compatible_rdp_version(version):
    # Permit distribution security revisions; do not pin an obsolete build suffix.
    return re.match(r'^2\.11\.5(?:$|[+~\-])', version.split(':', 1)[-1]) is not None


def installed_version(package):
    if not shutil.which('dpkg-query'):
        return None
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


def runtime_available():
    if not all(shutil.which(tool) for tool in ('xrandr', 'secret-tool')):
        return False
    if not all(probe([sys.executable, '-c', code])[0] for code in (GI_PROBE, LIBRARY_PROBE)):
        return False
    try:
        sonames = {'X11': 6, 'Xrender': 1, 'Xrandr': 2, 'Xinerama': 1,
                   'Xcursor': 1, 'Xfixes': 3, 'Xext': 6}
        for name, version in sonames.items():
            ctypes.CDLL(f'lib{name}.so.{version}')
    except OSError:
        return False
    return True


def package_version(package):
    choices = RDP_CHOICES.get(package, (package,))
    return next((version for choice in choices if (version := installed_version(choice))), None)


def ensure_dependencies():
    try:
        validate_target()  # User installation only; no OS/desktop/session restriction.
        installed = {package: package_version(package) for package in PACKAGES + RDP_PACKAGES}
        validate_existing_rdp(installed)
        if runtime_available():
            print('Dependências disponíveis.')
            return True
        if not all(shutil.which(tool) for tool in ('apt-get', 'apt-cache', 'dpkg-query')):
            raise DependencyError('Dependências ausentes. A instalação automática usa APT; '
                                  'instale GTK4/libadwaita, PyGObject, X11, xrandr, libsecret-tools '
                                  'e FreeRDP/WinPR 2.11.5 com o gerenciador da sua distribuição.')
        missing = [package for package, version in installed.items() if version is None]
        if not missing:
            raise DependencyError('Os pacotes estão presentes, mas as bibliotecas necessárias '
                                  'não carregaram. Verifique GTK4/libadwaita e FreeRDP/WinPR 2.11.5.')
        if not shutil.which('sudo'):
            raise DependencyError('sudo não está disponível para instalar as dependências.')
        print('Dependências ausentes: ' + ', '.join(missing), flush=True)
        print('Consultando as listas de pacotes já disponíveis; o instalador não executa apt-get update.',
              flush=True)
        requests = []
        for package in missing:
            if package in RDP_CHOICES:
                selected = None
                for choice in RDP_CHOICES[package]:
                    candidate = candidate_version(choice)
                    if compatible_rdp_version(candidate):
                        selected = choice + '=' + candidate
                        break
                if not selected:
                    raise DependencyError('As listas de pacotes disponíveis não oferecem '
                                          'FreeRDP/WinPR 2.11.5 para ' + package + '. '
                                          'Se estiverem desatualizadas, corrija eventuais '
                                          'falhas de repositório e execute sudo apt-get update '
                                          'manualmente antes de tentar novamente.')
                requests.append(selected)
            else:
                requests.append(package)
        options = ['--no-remove', '--no-install-recommends']
        try:
            run(['apt-get', '--simulate', *options, 'install', *requests])
        except DependencyError as error:
            raise DependencyError(str(error) + '\nA simulação usou as listas de pacotes '
                                  'existentes. Se estiverem desatualizadas, corrija '
                                  'eventuais falhas de repositório e execute '
                                  'sudo apt-get update manualmente.') from error
        print('Será solicitada a senha de administrador apenas para instalar esses pacotes.', flush=True)
        run(['sudo', '-v'], capture=False)
        run(['sudo', 'apt-get', '--yes', *options, 'install', *requests])
        for package in PACKAGES + RDP_PACKAGES:
            version = package_version(package)
            if not version or (package in RDP_PACKAGES and not compatible_rdp_version(version)):
                raise DependencyError('Dependência não ficou disponível: ' + package)
        print('Dependências instaladas. Continuando com o usuário atual.')
        return True
    except (DependencyError, OSError, ValueError, AttributeError) as error:
        print('Instalação interrompida: ' + str(error), flush=True)
        return False
