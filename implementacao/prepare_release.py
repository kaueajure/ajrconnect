#!/usr/bin/env python3
"""Stage the reviewed source tree and notes for a GitHub prerelease."""
from pathlib import Path
import argparse
import hashlib
import re
import tarfile

BASE = Path(__file__).resolve().parent
TAG = 'v6.0.0-beta.1'
ASSETS = ('ajr-connect-6-linux-x86_64.tar.gz', 'ajr-connect-6-sources.tar.gz')


def download_commands(repository):
    base_url = 'https://github.com/' + repository + '/releases/download/' + TAG
    return f'''```bash
mkdir -p ajr-connect-download
cd ajr-connect-download

curl -fL -o ajr-connect-6-linux-x86_64.tar.gz \\
  {base_url}/ajr-connect-6-linux-x86_64.tar.gz
curl -fL -o SHA256SUMS \\
  {base_url}/SHA256SUMS

sha256sum --ignore-missing -c SHA256SUMS
tar -xzf ajr-connect-6-linux-x86_64.tar.gz
cd ajr-connect
python3 install.py --check
python3 install.py
```

Prossiga para extração e instalação somente se o download e a verificação
de integridade passarem. Execute o instalador sem sudo, dentro da sessão
gráfica GNOME. Depois da instalação, saia da sessão e entre novamente.
'''


def release_notes(repository):
    return f'''# AJR Connect 6.0.0-beta.1 — versão de teste

Cliente RDP com interface GTK4/libadwaita, frontend FreeRDP personalizado
e AJR Bar para controlar sessões Windows no GNOME 46.

## Alvo desta versão

Zorin OS 18.1, Linux x86_64, GNOME 46, Wayland/XWayland e bibliotecas
FreeRDP/WinPR 2.11.5. O instalador verifica esses requisitos antes de modificar
arquivos e configurações. Outros ambientes ainda não foram validados.

## Recursos

- Seleção de monitor e abertura em janela ou fullscreen.
- Ctrl+Alt+Enter alterna fullscreen no monitor selecionado.
- Captura de teclado para Windows durante fullscreen ativo.
- AJR Bar no topo central: minimizar, sair de fullscreen e desconectar.
- Compartilhamento de pastas e área de transferência.
- Instalação por usuário, atalho no menu, backup e restauração.
- Novas instalações começam sem servidor, usuário ou pastas preenchidos.

O perfil usa renderização por software e não ativa `/gfx`, `/gdi:hw`
ou a floatbar visual nativa do FreeRDP.

## Estado da validação

Esta é uma versão de teste. A instalação em um Zorin recém-instalado ainda
não foi validada. Na máquina de desenvolvimento, foram aprovados dez testes
do instalador, incluindo preservação de configurações e restauração em
diretórios de usuário temporários, com configurações GNOME em memória.
Os pacotes extraídos passaram na verificação de compatibilidade e o frontend
foi recompilado usando o pacote de fontes.

O cliente foi testado com uma VM real em dois monitores, incluindo a
atualização da imagem durante fullscreen. A verificação do instalador não
substitui um teste completo em outra instalação do sistema.

Reconecte ao mudar resolução ou escala dos monitores. A AJR Bar é destinada
ao GNOME 46 e requer um novo login após a instalação.

## Baixar e instalar pelo terminal

{download_commands(repository)}
## Arquivos

- `{ASSETS[0]}`: aplicativo, cliente compilado, extensão e instalador.
- `{ASSETS[1]}`: fontes correspondentes, cabeçalhos e script de compilação.
- `SHA256SUMS`: hashes para conferir os downloads.

Licença Apache 2.0; os avisos originais do FreeRDP são preservados.
Relate falhas em https://github.com/{repository}/issues com o sistema,
versões, monitor e passos para reproduzir. Não inclua senhas nem dados
pessoais dos registros ou capturas.
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
        'Versão atual: **6.0.0-beta.1**. A instalação em um Zorin recém-instalado\n'
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
