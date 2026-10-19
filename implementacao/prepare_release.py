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
    return f'''# AJR Connect {TAG.removeprefix('v')} — aparência, resolução e RAM da VM

## Mudanças

- Os três modos de qualidade solicitam cores em 32 bits, temas, papel de parede
  e suavização de fontes. O preset de rede deixou de alterar essas preferências.
- Resolução do Windows salva por conexão: automática pelo monitor, 4K, QHD,
  1080p, 720p, 480p e 360p, com ajuste da imagem à janela local.
- Monitoramento opcional da RAM física usada dentro do Windows, com limite por
  conexão e aviso para continuar ou desconectar sem desligar a VM.
- Coletor iniciado pelo usuário em **Mais opções → RAM da VM**, compartilhamento
  temporário por sessão e descarte de leituras inválidas ou antigas.
- Perfis, senhas no chaveiro, pastas compartilhadas e reconexão preservados.

A mudança de azul para roxo relatada ainda precisa de reprodução e comparação
visual. Esta versão não é apresentada como correção comprovada desse sintoma.

## Atualizar

Desconecte o Windows antes de instalar. Execute no terminal Linux, sem sudo:

{download_commands(repository)}
Também é possível usar **Mais opções → Atualizações**, ativar **Incluir versões
de teste**, verificar, instalar e reiniciar o aplicativo.

## Validação

- 86 testes automatizados aprovados, cobrindo resolução, parâmetros visuais reais do FreeRDP,
  monitoramento de RAM, perfis, reconexão, instalação e atualização.
- Verificações isoladas da interface, teclado e integração GNOME.
- Pacotes Linux e fontes com SHA256 e verificação de dados privados.

Os testes de publicação não abrem a VM nem consultam o chaveiro real.
A versão é de teste, para Linux x86_64 com FreeRDP/WinPR 2.11.5.
A validação em uma instalação limpa continua pendente.
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
