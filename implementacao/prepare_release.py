#!/usr/bin/env python3
"""Stage the reviewed source tree and notes for a GitHub prerelease."""
from pathlib import Path
import argparse
import hashlib
import re
import tarfile

BASE = Path(__file__).resolve().parent
TAG = 'v6.0.0-beta.5'
ASSETS = ('ajr-connect-6-linux-x86_64.tar.gz', 'ajr-connect-6-sources.tar.gz')


def download_commands(repository):
    account, name = repository.split('/', 1)
    url = f'https://{account}.github.io/{name}/install.sh'
    return f'''```bash
curl -fsSL {url} | bash
```

O comando baixa o pacote, confere a integridade e executa o instalador.
Execute com seu usuário, sem sudo. Para atualizar, execute novamente o mesmo
comando, reabra o aplicativo e reconecte ao Windows. A primeira instalação ou
a migração da extensão antiga pode exigir um único novo login para ativar
a AJR Bar; atualizações rotineiras da barra são aplicadas na sessão atual.
'''


def release_notes(repository):
    return f'''# AJR Connect {TAG.removeprefix('v')} — versão de teste

Cliente RDP com interface GTK4/libadwaita, frontend FreeRDP personalizado
e AJR Bar para controlar sessões Windows no GNOME 46.

## Mudanças desta versão

- O botão de pasta abre diretamente o seletor GTK, permitindo navegar pelos
  diretórios locais sem depender do portal de arquivos. Pastas de rede precisam
  estar montadas como diretórios locais antes de serem compartilhadas.
- Várias conexões podem ser salvas com nome, servidor, usuário e preferências
  próprias. A configuração anterior é migrada automaticamente. Senhas lembradas
  ficam no chaveiro e são identificadas por servidor e usuário; não entram no JSON.
- O atalho de tela cheia pode ser alterado em **Tela e teclado**. A combinação
  inicial continua sendo Ctrl+Alt+Enter.
- A captura de teclado pode valer somente em tela cheia, também em janela ou
  permanecer no computador local. Alt+Tab, Windows/Super sozinha e Alt+F4 têm
  prioridades individuais; essa combinação exige AJR Bar ativa no GNOME 46.
  Super+R e outras combinações com Super seguem a captura geral do teclado.
- A AJR Bar usa uma ponte fixa e módulos recarregáveis para aplicar atualizações
  na sessão atual. A primeira instalação, a migração da extensão antiga e
  mudanças excepcionais na ponte ainda podem exigir um novo login. O instalador
  não encerra conexões RDP abertas; reabra o aplicativo e reconecte para carregar
  a nova interface e o novo cliente.
- A restauração de backups com a ponte recarregável também funciona na sessão
  atual. Falhas ao carregar a nova barra preservam ou tentam restaurar a anterior.

## Instalação sem bloqueio de ambiente

O instalador não exige uma distribuição, versão do GNOME, X11, Wayland
ou sessão gráfica ativa específicos. Verifica a arquitetura e as dependências
necessárias para executar o cliente. O pacote compilado é Linux x86_64,
com GTK4/libadwaita, PyGObject, X11 e FreeRDP/WinPR 2.11.5.

A instalação automática usa APT, aceita pacotes RDP com ou sem `t64` e usa as
listas de pacotes existentes, sem executar `apt-get update`.
Sem APT, a instalação segue quando as dependências estão disponíveis;
se faltarem, orienta a instalá-las com o gerenciador da distribuição.

A AJR Bar é opcional para GNOME 46. Em outros desktops, use os controles
na janela do aplicativo e o atalho configurado de tela cheia. A instalação e a restauração
preservam extensões e autostart existentes quando essa integração não é aplicada.

## Recursos

- Seleção de monitor e abertura em janela ou fullscreen.
- Atalho personalizável para fullscreen no monitor selecionado.
- Captura de teclado configurável para Windows ou computador local.
- AJR Bar no topo central: minimizar, sair de fullscreen e desconectar.
- Compartilhamento de pastas e área de transferência.
- Instalação por usuário, atalho no menu, backup e restauração.
- Instalação automática das dependências ausentes pelo APT, com sudo somente nessa etapa.
- Novas instalações começam sem servidor, usuário ou pastas preenchidos.

O perfil usa renderização por software e não ativa `/gfx`, `/gdi:hw`
ou a floatbar visual nativa do FreeRDP.

## Estado da validação

Esta é uma versão de teste. A instalação em um Zorin recém-instalado ainda
não foi validada. Foram aprovados 50 testes automatizados, incluindo perfis,
seletor de pastas, gravação do atalho, atualização da integração, preservação
de configurações e instalação/restauração em diretórios de usuário temporários.
O teste nativo de teclado passou em Xvfb. Em uma sessão GNOME 46 isolada, a
atualização real da barra, a restauração de módulos anteriores e a recuperação
de falhas de importação/ativação passaram sem reiniciar o GNOME Shell.
Os pacotes extraídos passaram na verificação de compatibilidade e o frontend
foi recompilado usando o pacote de fontes.

O cliente foi testado com uma VM real em dois monitores, incluindo a
atualização da imagem durante fullscreen. A verificação do instalador não
substitui um teste completo em outra instalação do sistema.

Reconecte ao mudar resolução ou escala dos monitores. A AJR Bar é destinada
ao GNOME 46. A primeira ativação ou a migração da extensão antiga pode exigir
um novo login; atualizações rotineiras usam a ponte recarregável na sessão atual.

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
