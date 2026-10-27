#!/usr/bin/env python3
"""Stage the reviewed source tree and notes for a GitHub prerelease."""
from pathlib import Path
import argparse
import hashlib
import re
import tarfile
from version import APP_VERSION

BASE = Path(__file__).resolve().parent
TAG = 'v' + APP_VERSION
ASSETS = ('ajr-connect-6-linux-x86_64.tar.gz', 'ajr-connect-6-sources.tar.gz')


def download_commands(repository):
    account, name = repository.split('/', 1)
    url = f'https://{account}.github.io/{name}/install.sh'
    return f'''```bash
curl -fsSL {url} | bash
```

O comando baixa o pacote, confere a integridade e executa o instalador.
Execute com seu usuário, sem sudo. Para atualizar, execute novamente o mesmo
comando, reabra o aplicativo e reconecte ao Windows. A AJR Bar é integrada
ao cliente RDP e dispensa novo login. Para atalhos locais, o sistema pode
solicitar autorização de teclado, com opção de lembrar a seleção.
'''


def release_notes(repository):
    return f'''# AJR Connect {TAG.removeprefix('v')} — detecção local do Docker

## Mudanças

- Detecta sockets do Docker que são links simbólicos e evita caminhos duplicados.
- Consulta o contexto local selecionado e o endpoint Unix configurado no Docker.
- Respeita o diretório de execução configurado para Docker sem root.
- Amplia a busca de ferramentas para diretórios administrativos do sistema.
- Diagnóstico no aplicativo mostra o cliente Docker, os sockets do sistema e do
  usuário e o endpoint local configurado.
- Mantém a busca restrita a máquinas locais, sem usar contextos remotos.
- Preserva a correção dos módulos ausentes na instalação da beta 17.

## Instalar ou atualizar

{download_commands(repository)}
Se o aplicativo ainda abre, também é possível atualizar em
**Mais opções → Atualizações**, no canal **Versões de teste**.
Se a versão anterior não abre por falta de módulo, o instalador desta versão
repara os arquivos automaticamente. Não é necessário copiar módulos manualmente.

## Validação

- Instalação nova, atualização de instalação incompleta e rollback em diretórios isolados.
- Importação da interface usando somente os arquivos instalados.
- Testes de descoberta Docker, contexto local, sockets por link, diretório
  rootless, controle das máquinas, diagnósticos e rejeição de endpoints remotos.
- Verificação de compatibilidade, atualização e recuperação de falhas.
- Pacotes Linux e fontes com SHA256.

Limitação conhecida: o teste gráfico de atualização falha na mensagem de
cancelamento do download; a instalação e a recuperação passaram nos testes.
A instalação em um Zorin recém-instalado ainda precisa ser validada.
As correções de detecção ainda precisam ser confirmadas nos PCs afetados.

Versão de teste para Linux x86_64 com FreeRDP/WinPR 2.11.5.
'''


def prepare(repository, output):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', repository):
        raise ValueError('Informe o repositório como CONTA/REPOSITORIO.')
    dist = BASE.parent / 'dist'
    expected = {}
    for line in (dist / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        expected[name] = digest
    for name in ASSETS:
        if hashlib.sha256((dist / name).read_bytes()).hexdigest() != expected.get(name):
            raise ValueError('Integridade inválida: ' + name)
    repository_dir = output / 'ajr-connect'
    if repository_dir.exists():
        raise FileExistsError('O diretório de publicação já existe: ' + str(repository_dir))
    output.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dist / ASSETS[1]) as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if (not parts or parts[0] != 'ajr-connect-sources' or '..' in parts
                    or Path(member.name).is_absolute() or member.issym() or member.islnk()):
                raise ValueError('Entrada inválida no pacote de fontes.')
        archive.extractall(output, filter='data')
    (output / 'ajr-connect-sources').rename(repository_dir)
    original = (repository_dir / 'README.md').read_text()
    original = original.replace('# AJR Connect 6\n',
        '# AJR Connect 6 — versão de teste\n\n'
        f'Versão atual: **{TAG.removeprefix("v")}**. A instalação em um Zorin recém-instalado\n'
        'ainda precisa ser validada.\n\n'
        '## Download da versão de teste\n\n' + download_commands(repository) + '\n', 1)
    (repository_dir / 'README.md').write_text(original)
    (repository_dir / '.gitignore').write_text(
        '__pycache__/\n*.pyc\n/native/ajr-freerdp\n/dist/\n*.log\n')
    notes = output / ('RELEASE-' + TAG + '.md')
    notes.write_text(release_notes(repository))
    print('Fontes para publicação:', repository_dir)
    print('Notas da versão:', notes)
    print('Destino:', repository)
    print('Preparação concluída; este comando não publica arquivos.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, help='CONTA/REPOSITORIO no GitHub')
    parser.add_argument('--output', type=Path, default=BASE.parent / 'publicacao')
    args = parser.parse_args()
    prepare(args.repo, args.output.resolve())
