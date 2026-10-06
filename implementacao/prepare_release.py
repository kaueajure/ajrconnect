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
comando, reabra o aplicativo e reconecte ao Windows. A primeira instalação ou
a migração da extensão antiga pode exigir um único novo login para ativar
a AJR Bar; atualizações rotineiras da barra são aplicadas na sessão atual.
'''


def release_notes(repository):
    return f'''# AJR Connect {TAG.removeprefix('v')} — interface V2

Cliente RDP para Linux com GTK4/libadwaita e AJR Bar. Esta publicação continua
no canal de versões de teste, para Linux x86_64 e FreeRDP/WinPR 2.11.5.

## Mudanças

- Interface V2 com superfícies neutras e violeta como accent, em temas claro
  e escuro. Hero ilustrado removido, sidebar simplificada e navegação leve.
- Dados de acesso em duas colunas na janela ampla e empilhados nas menores.
  Preferências separadas e rodapé compacto com Salvar e Conectar.
- Controles de tela cheia, modo janela, minimizar e desconectar contextuais.
  Reconexão mantém próxima tentativa, spinner e cancelamento.
- Tela e teclado com grupos de tela, atalhos e regras personalizadas;
  cada regra identifica seu destino e permite editar ou remover.
- Compartilhamento com ação no estado vazio, caminho Linux e nome no Windows,
  menu por pasta e grupo próprio de área de transferência.
- Diálogos de atalho, pasta e atualização alinhados à V2, com rolagem e ações
  acessíveis em janelas menores. Mensagens de erro recebem foco e podem ser copiadas.
- Atualização pelo aplicativo e reconexão automática, antes presentes nos
  fontes de desenvolvimento, agora incluídas no download publicado.

## Atualizar

Em versões com atualização integrada, abra **Mais opções → Atualizações**,
ative **Incluir versões de teste**, escolha **Verificar atualizações** e
**Baixar e atualizar**. Encerre a conexão RDP antes de instalar e escolha
**Reiniciar aplicativo** ao concluir.

Em versões anteriores, ou para instalar pelo terminal:

{download_commands(repository)}
## Preservação e compatibilidade

Perfis, credenciais no chaveiro, preferências, pastas e regras de teclado
mantêm seus formatos e comportamentos. A apresentação permanece separada do
controlador de sessão. O instalador cria backup e preserva configurações.
Não altera o cliente RDP do sistema nem instala dependências visuais externas.

O pacote requer GTK4/libadwaita, PyGObject, bibliotecas X11 e FreeRDP/WinPR
2.11.5. Dependências ausentes são instaladas por APT quando disponível,
sem atualizar automaticamente as listas de pacotes. Execute sem sudo;
a senha de administrador é solicitada somente quando faltam dependências.
A AJR Bar é opcional para GNOME 46; outros desktops usam os controles do cliente.

## Validação

- 70 testes automatizados aprovados, incluindo os 69 anteriores e a nova
  regressão da interface V2.
- Política de teclado nativa aprovada em um servidor X privado.
- Integração, atualização e rollback da AJR Bar aprovados no GNOME 46 isolado.
- 31 capturas de interface; temas, diálogos, pastas, erros e controles de sessão
  revisados em 1120 × 820, 680 × 760 e 620 × 480.
- Verificações de overflow horizontal, ações fixas, foco de erros e senha.

A validação desta refatoração foi isolada, sem consultar credenciais do usuário
ou abrir uma nova sessão RDP real. A instalação em um Zorin recém-instalado e
reconexões contra um servidor Windows real ainda precisam de validação.

## Arquivos

- `{ASSETS[0]}`: aplicativo, cliente compilado, extensão e instalador.
- `{ASSETS[1]}`: fontes correspondentes, cabeçalhos e script de compilação.
- `SHA256SUMS`: hashes SHA256 dos dois pacotes.

Licença Apache 2.0; avisos do FreeRDP preservados. Relate falhas em
https://github.com/{repository}/issues, sem senhas ou dados pessoais.
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
