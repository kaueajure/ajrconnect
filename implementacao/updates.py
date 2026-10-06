"""Release discovery, verified downloads and per-user application updates."""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from urllib.parse import urlparse
from core import APP_DIR, DATA_DIR
from version import APP_VERSION, REPOSITORY

ASSET = 'ajr-connect-6-linux-x86_64.tar.gz'
MAX_DOWNLOAD = 256 * 1024 * 1024
MAX_EXTRACTED = 512 * 1024 * 1024
INSTALL_LOG = DATA_DIR / 'updates/update.log'


class UpdateCancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise UpdateCancelled('Download cancelado.')


def version_key(value):
    match = re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'
        r'(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?', value)
    if not match:
        raise ValueError('Versão inválida: ' + value)
    major, minor, patch, pre = match.groups()
    identifiers = tuple((0, int(part)) if part.isdigit() else (1, part)
                        for part in pre.split('.')) if pre else ()
    return int(major), int(minor), int(patch), pre is None, identifiers


@dataclass(frozen=True)
class Release:
    tag: str
    size: int
    digest: str = ''

    def url(self, name):
        return f'https://github.com/{REPOSITORY}/releases/download/{self.tag}/{name}'

    @property
    def page(self):
        return f'https://github.com/{REPOSITORY}/releases/tag/{self.tag}'


def select_release(releases, current=APP_VERSION, include_prereleases=True):
    candidates = []
    for entry in releases:
        if not isinstance(entry, dict) or entry.get('draft') or \
                entry.get('prerelease') and not include_prereleases:
            continue
        try:
            tag = entry['tag_name']
            key = version_key(tag)
            if key <= version_key(current) or ('-' in tag and not include_prereleases):
                continue
            assets = entry.get('assets', [])
            runtime = next(asset for asset in assets if asset.get('name') == ASSET
                           and asset.get('state') == 'uploaded')
            if not any(asset.get('name') == 'SHA256SUMS' and asset.get('state') == 'uploaded'
                       for asset in assets):
                continue
            size = runtime['size']
            if not isinstance(size, int) or not 0 < size <= MAX_DOWNLOAD:
                continue
            digest = runtime.get('digest') or ''
            candidates.append((key, Release(tag, size, digest)))
        except (ValueError, KeyError, TypeError, StopIteration, AttributeError):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def open_url(url):
    request = urllib.request.Request(url, headers={'User-Agent': f'AJR-Connect/{APP_VERSION}',
        'Accept': 'application/vnd.github+json' if 'api.github.com/' in url else 'application/octet-stream',
        'X-GitHub-Api-Version': '2022-11-28'})
    response = urllib.request.urlopen(request, timeout=10)
    parsed = urlparse(response.geturl())
    if parsed.scheme != 'https' or parsed.hostname not in ('github.com', 'api.github.com') \
            and not (parsed.hostname or '').endswith('.githubusercontent.com'):
        response.close()
        raise ValueError('O download foi redirecionado para um endereço não permitido.')
    return response


def read_small(url, limit, cancel=None):
    check_cancel(cancel)
    with open_url(url) as response:
        content = response.read(limit + 1)
    check_cancel(cancel)
    if len(content) > limit:
        raise ValueError('A resposta do servidor excede o tamanho permitido.')
    return content


def check_updates(*, current=APP_VERSION, include_prereleases=True, cancel=None):
    url = f'https://api.github.com/repos/{REPOSITORY}/releases?per_page=100'
    entries = json.loads(read_small(url, 4 * 1024 * 1024, cancel))
    if not isinstance(entries, list):
        raise ValueError('O servidor não retornou uma lista de versões válida.')
    return select_release(entries, current, include_prereleases)


def checksum_for(content, name=ASSET):
    for line in content.decode('ascii').splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(.+)', line)
        if match and match[2] == name:
            return match[1].lower()
    raise ValueError('O pacote não possui um SHA256 válido na versão publicada.')


def download_release(release, destination, cancel, progress):
    expected = checksum_for(read_small(release.url('SHA256SUMS'), 65536, cancel))
    if release.digest and release.digest != 'sha256:' + expected:
        raise ValueError('Os hashes publicados para o pacote não correspondem.')
    digest, count = hashlib.sha256(), 0
    deadline = time.monotonic() + 180
    with open_url(release.url(ASSET)) as response, destination.open('wb') as stream:
        while True:
            check_cancel(cancel)
            if time.monotonic() > deadline:
                raise TimeoutError('O download excedeu o tempo limite. Tente novamente.')
            chunk = response.read(65536)
            if not chunk:
                break
            count += len(chunk)
            if count > release.size or count > MAX_DOWNLOAD:
                raise ValueError('O pacote excede o tamanho publicado.')
            stream.write(chunk)
            digest.update(chunk)
            progress('download', count / release.size)
    check_cancel(cancel)
    if count != release.size or digest.hexdigest() != expected:
        raise ValueError('O arquivo baixado falhou na verificação de integridade.')


def extract_package(archive_path, target):
    total, paths = 0, set()
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        if len(members) > 4096:
            raise ValueError('O pacote contém arquivos demais.')
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or \
                    path.parts[0] != 'ajr-connect' or not (member.isfile() or member.isdir()) \
                    or path in paths:
                raise ValueError('O pacote contém uma entrada não permitida.')
            paths.add(path)
            total += member.size
            if total > MAX_EXTRACTED:
                raise ValueError('O pacote extraído excede o tamanho permitido.')
        # Extract only ordinary files/directories into the private staging tree.
        for member in members:
            path = target.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, path.open('xb') as output:
                    shutil.copyfileobj(source, output)
                path.chmod(0o755 if member.mode & 0o111 else 0o644)
    return target / 'ajr-connect'


def installed_application():
    return APP_DIR.resolve() == (DATA_DIR / 'app').resolve()


def apply_update(release, cancel, progress):
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('A atualização disponível é para Linux x86_64.')
    if not installed_application():
        raise ValueError('Atualize a instalação do aplicativo; este é um diretório de desenvolvimento.')
    with tempfile.TemporaryDirectory(prefix='ajr-update-') as directory:
        staging = Path(directory)
        archive = staging / ASSET
        download_release(release, archive, cancel, progress)
        progress('verify', 1)
        package = extract_package(archive, staging)
        # Read the release identity as data; never import code before validation.
        identity = (package / 'version.py').read_text()
        match = re.search(r"^APP_VERSION = ['\"]([^'\"]+)['\"]$", identity, re.MULTILINE)
        if not match or version_key(match[1]) != version_key(release.tag):
            raise ValueError('A versão do pacote não corresponde à publicação.')
        if not (package / 'install.py').is_file():
            raise ValueError('O pacote não contém o instalador.')
        check_cancel(cancel)
        progress('install', 1)
        INSTALL_LOG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with INSTALL_LOG.open('w') as log:
            os.chmod(INSTALL_LOG, 0o600)
            try:
                result = subprocess.run([sys.executable, str(package / 'install.py'), '--update'],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            except subprocess.TimeoutExpired:
                subprocess.run([sys.executable, str(package / 'install.py'), '--recover-update'],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=60, check=True)
                raise RuntimeError('A atualização excedeu o tempo limite. A instalação anterior foi restaurada.')
        if result.returncode:
            raise RuntimeError('Não foi possível instalar a atualização. Consulte ' + str(INSTALL_LOG))
    return release.tag.removeprefix('v')


def restart_after_exit(pid):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            launcher = Path.home() / '.local/bin/ajr-connect'
            os.execv(sys.executable, [sys.executable, str(launcher)])
        time.sleep(.1)
    raise RuntimeError('O aplicativo anterior não encerrou a tempo.')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--restart':
        restart_after_exit(int(sys.argv[2]))
