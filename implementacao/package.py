#!/usr/bin/env python3
"""Build clean runtime/source archives from explicit inputs. Never install/publish."""
from pathlib import Path
import argparse
import gzip
import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile

BASE = Path(__file__).resolve().parent
RUNTIME_FILES = ('ajr_app.py', 'ui.py', 'dialogs.py', 'keyboard.py', 'keyboard_portal.py', 'core.py', 'integration.py', 'x11.py', 'ajr-control', 'ajr-connect',
                 'enable-extension.py', 'ajr-connect.desktop.in', 'install.py',
                 'rollback.py', 'check_compatibility.py')
RUNTIME_FILES += ('dependencies.py',)
RUNTIME_FILES += ('version.py', 'reconnect.py', 'updates.py', 'update_dialog.py')
SOURCE_FILES = ('DESIGN.md', 'native/build.py', 'native/ajr.c', 'native/ajr_bar.c', 'native/ajr.h',
                'native/ajr-freerdp.patch', 'tests/test_compatibility.py',
                'tests/test_distribution.py')
SOURCE_FILES += ('tests/test_dependencies.py',)
SOURCE_FILES += ('tests/test_preferences.py', 'tests/check_keyboard_policy.py',
                 'tests/keyboard_policy.c')
SOURCE_FILES += ('tests/test_integration_update.py', 'tests/check_live_update.py', 'tests/check_desktop_ui.py')
SOURCE_FILES += ('tests/test_keyboard_portal.py', 'tests/check_portal_session.py')
SOURCE_FILES += ('tests/test_updates.py', 'tests/test_reconnect.py')
SOURCE_TREES = ('native/vendor/FreeRDP-2.11.5/client/X11',
                'native/vendor/FreeRDP-2.11.5/resources',
                'native/sdk/usr/include/freerdp2', 'native/sdk/usr/include/winpr2')
PRIVATE_MARKERS = (str(Path.home()).encode(), str(BASE.parent).encode())


def copy_file(source, target, executable=False):
    if source.is_symlink() or not source.is_file():
        raise ValueError('Entrada inválida: ' + str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o755 if executable else 0o644)


def stage_runtime(target, binary):
    for name in RUNTIME_FILES:
        copy_file(BASE / name, target / name, name in ('ajr-connect', 'ajr-control'))
    for name in ('extension.js', 'integration.js', 'stylesheet.css', 'metadata.json'):
        copy_file(BASE / 'extensao' / name, target / 'extensao' / name)
    for name in ('style.css', 'ajr-connect.svg', 'workspace.svg'):
        copy_file(BASE / 'assets' / name, target / 'assets' / name)
    copy_file(binary, target / 'native/ajr-freerdp', True)
    copy_file(BASE / 'distribution/README.md', target / 'README.md')
    copy_file(BASE / 'distribution/NOTICE.txt', target / 'NOTICE.txt')
    copy_file(BASE / 'LICENSE', target / 'LICENSE')
    copy_file(BASE / 'distribution/AJR-LICENSE.txt', target / 'licenses/AJR.txt')
    copy_file(BASE / 'native/vendor/FreeRDP-2.11.5/LICENSE', target / 'licenses/Apache-2.0.txt')


def stage_sources(target, runtime):
    for source in sorted(runtime.rglob('*')):
        if source.is_file() and source.relative_to(runtime).as_posix() != 'native/ajr-freerdp':
            copy_file(source, target / source.relative_to(runtime))
    for name in SOURCE_FILES:
        copy_file(BASE / name, target / name)
    for directory in SOURCE_TREES:
        for source in sorted((BASE / directory).rglob('*')):
            if source.is_file():
                copy_file(source, target / source.relative_to(BASE))
    vendor = target / 'native/vendor/FreeRDP-2.11.5'
    copy_file(BASE / 'native/vendor/FreeRDP-2.11.5/LICENSE', vendor / 'LICENSE')
    for name in ('xfreerdp.h', 'xf_client.c', 'xf_event.c', 'xf_keyboard.c'):
        source = vendor / 'client/X11' / name
        source.write_text('/* Modified for AJR Connect 6: fullscreen, keyboard and X11 integration.\n'
                          ' * See native/ajr-freerdp.patch and NOTICE.txt. */\n' + source.read_text())
    (target / 'BUILD.md').write_text('''# Compilar o frontend AJR

Neste diretório, execute `python3 native/build.py`.
São necessários GCC, bibliotecas FreeRDP/WinPR 2.11.5 e bibliotecas de
desenvolvimento X11/XRender/XRandR/Xinerama/XCursor/XFixes/Xext, Cairo/Pango
e pkg-config (libcairo2-dev, libpango1.0-dev).
Os cabeçalhos FreeRDP/WinPR 2.11.5 correspondentes estão incluídos.
O resultado fica em `native/ajr-freerdp`; depois disso, o instalador pode
verificar o ambiente com `python3 install.py --check`.

Os fontes X11 incluídos já contêm as alterações AJR. O patch é fornecido
como registro; não aplique o patch novamente sobre esses fontes.
''')


def audit_tree(target):
    for source in target.rglob('*'):
        if source.is_symlink():
            raise ValueError('Link simbólico não permitido: ' + str(source))
        if source.is_file():
            content = source.read_bytes()
            if any(marker in content for marker in PRIVATE_MARKERS):
                raise ValueError('Dado privado encontrado: ' + str(source.relative_to(target)))


def archive_tree(target, output, root_name):
    # Normalize archive metadata; no local username, absolute paths or timestamps.
    with output.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as stream:
        with tarfile.open(fileobj=stream, mode='w') as archive:
            for source in [target, *sorted(target.rglob('*'))]:
                name = root_name if source == target else root_name + '/' + source.relative_to(target).as_posix()
                info = archive.gettarinfo(str(source), arcname=name)
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ''
                info.mode = 0o755 if source.is_dir() or source.stat().st_mode & 0o111 else 0o644
                if source.is_file():
                    with source.open('rb') as content:
                        archive.addfile(info, content)
                else:
                    archive.addfile(info)


def build_packages(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ajr-package-') as directory:
        temporary = Path(directory)
        binary = temporary / 'ajr-freerdp'
        env = dict(os.environ, AJR_BUILD_RELEASE='1', AJR_BUILD_OUTPUT=str(binary))
        subprocess.run(['python3', str(BASE / 'native/build.py')], env=env, check=True)
        subprocess.run(['strip', '--strip-unneeded', str(binary)], check=True)
        runtime = temporary / 'runtime'
        sources = temporary / 'sources'
        stage_runtime(runtime, binary)
        stage_sources(sources, runtime)
        audit_tree(runtime)
        audit_tree(sources)
        bundles = []
        for tree, name, root in ((runtime, 'ajr-connect-6-linux-x86_64.tar.gz', 'ajr-connect'),
                                 (sources, 'ajr-connect-6-sources.tar.gz', 'ajr-connect-sources')):
            archive = output / name
            archive_tree(tree, archive, root)
            bundles.append(archive)
        (output / 'SHA256SUMS').write_text(''.join(
            hashlib.sha256(bundle.read_bytes()).hexdigest() + '  ' + bundle.name + '\n'
            for bundle in bundles))
    for bundle in bundles:
        print('Pacote gerado:', bundle)
    print('Hashes:', output / 'SHA256SUMS')
    print('Preparação local concluída; nenhum arquivo foi publicado ou instalado.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=BASE.parent / 'dist')
    args = parser.parse_args()
    build_packages(args.output.resolve())
