# AJR Connect — versão de teste

Cliente RDP com interface GTK4/libadwaita, frontend FreeRDP personalizado e
AJR Bar para controlar sessões Windows no GNOME 46.

Versão de teste: **6.0.0-beta.4**. A instalação em um Zorin recém-instalado
ainda precisa ser validada.

## Instalação em outras distribuições

O download e a instalação não bloqueiam por nome ou versão da distribuição,
versão do GNOME, X11, Wayland ou ausência de uma sessão gráfica ativa.
O pacote compilado é Linux x86_64 e precisa de GTK4/libadwaita, PyGObject,
bibliotecas X11 e FreeRDP/WinPR 2.11.5 para executar.
O instalador verifica a arquitetura antes de instalar dependências e verifica
as bibliotecas exigidas pelo binário, incluindo glibc, antes de copiar o aplicativo.
O pacote não é exclusivo do Zorin, mas essas dependências precisam ser compatíveis.
Para outra arquitetura ou bibliotecas de sistema mais antigas, compile os fontes
no sistema de destino; isso também exige as dependências de desenvolvimento.

Dependências ausentes são instaladas automaticamente em sistemas com APT,
aceitando os nomes de pacotes com ou sem `t64`. Em outros gerenciadores,
a instalação segue se as dependências já estão disponíveis; se faltarem,
o instalador informa o que instalar.
O instalador usa as listas de pacotes que já existem no computador e não
executa `apt-get update`. A instalação depende de elas conterem versões
disponíveis para as dependências; se estiverem vazias ou antigas, será
necessário atualizá-las manualmente após corrigir eventuais fontes com erro.

A AJR Bar é uma integração opcional para GNOME 46. Em outros desktops ou
versões do GNOME, o cliente é instalado com os controles na janela do
aplicativo e Ctrl+Alt+Enter para alternar fullscreen.

O AJR Connect conecta a servidores Windows por RDP, incluindo VMs hospedadas
em Docker. Docker não é necessário no computador que executa o cliente.

## Download e instalação

Execute um único comando no terminal da sessão gráfica:

```bash
curl -fsSL https://kaueajure.github.io/ajrconnect/install.sh | bash
```

O comando baixa a versão de teste, confere a integridade e executa o
instalador. Ele verifica o ambiente antes de alterar arquivos, preserva as
configurações existentes e cria um backup. Execute **sem sudo**.
Se faltarem dependências, a senha de administrador será solicitada para
instalá-las pelo APT. Apenas pacotes ausentes são solicitados; as bibliotecas
FreeRDP/WinPR devem manter a versão 2.11.5. O instalador simula a transação
antes de executá-la, não permite remoções e não faz downgrade automático.
Se todas as dependências já estiverem instaladas, não usa sudo.
Se a AJR Bar for instalada, saia da sessão e entre novamente para carregá-la.

Para apenas verificar o ambiente:

```bash
curl -fsSL https://kaueajure.github.io/ajrconnect/install.sh | bash -s -- --check
```

Abra AJR Connect pelo menu de aplicativos. Configure servidor, usuário,
senha, monitor e pastas compartilhadas. Novas instalações começam com esses
campos vazios; configurações existentes são preservadas.

## Controles

- Ctrl+Alt+Enter alterna entre janela e fullscreen no monitor selecionado.
- Em fullscreen ativo, o teclado é capturado para encaminhar atalhos ao Windows.
- Em janela, os atalhos globais ficam com o Linux.
- No GNOME 46, a AJR Bar no topo central permite minimizar, sair de fullscreen e desconectar.
- Os mesmos controles estão disponíveis na janela do aplicativo.

O cliente preserva o compartilhamento de pastas e usa renderização por software,
sem ativar `/gfx`, `/gdi:hw` ou a floatbar visual nativa do FreeRDP.
Reconecte depois de alterar resolução ou escala dos monitores.

## Compilar e testar

O repositório contém o código em `implementacao/`. GCC e bibliotecas de
desenvolvimento X11/XRender/XRandR/Xinerama/XCursor/XFixes/Xext são necessários,
além das bibliotecas FreeRDP/WinPR 2.11.5 do sistema.

```bash
cd implementacao
python3 native/build.py
python3 install.py --check
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Para gerar os pacotes localmente, execute `python3 package.py` a partir de
`implementacao/`. Os arquivos são gerados em `dist/`, fora do controle de versão.

## Validação e problemas

Os testes de compatibilidade, instalação e restauração passaram na
máquina de desenvolvimento, usando diretórios de usuário temporários e
configurações GNOME em memória. Os pacotes extraídos passaram na verificação
de compatibilidade e o cliente foi recompilado a partir dos fontes distribuídos.
O cliente também foi testado com uma VM real em dois monitores.

Os testes também cobrem instalação sem sessão gráfica, esquemas GNOME ausentes,
preservação de extensões existentes, nomes de pacotes sem `t64`, dependências
pré-instaladas sem APT e bloqueio de arquivos com integridade incorreta.

As validações em uma instalação limpa e em outros desktops reais ainda estão pendentes.

### APT: chave de repositório ausente

Se aparecer `NO_PUBKEY A2FB21D5A8772835` junto de `deb.anydesk.com`,
o APT interrompeu a atualização por uma falha na assinatura do repositório
do AnyDesk. O download do AJR já pode ter sido concluído corretamente.
O aviso `doesn't support architecture 'i386'` de outro repositório não é
a causa dessa interrupção e não informa a arquitetura principal da máquina.

Corrija a chave e a configuração da fonte do AnyDesk conforme as
[instruções oficiais](https://deb.anydesk.com/howto.html), conferindo também
entradas antigas ou duplicadas em `/etc/apt/sources.list` e
`/etc/apt/sources.list.d/`. Se não utiliza esse repositório, desative somente
essa fonte pelo gerenciador de repositórios do sistema. Depois execute
`sudo apt-get update` e repita a instalação do AJR **sem sudo**.
O instalador consulta as listas de pacotes já existentes, sem executar
`apt-get update`. Se não houver versões disponíveis ou o download de um
pacote falhar, informa o erro e interrompe antes de copiar o aplicativo.
Não altera chaves ou fontes de outros aplicativos e mantém a verificação
de assinatura dos pacotes.

Relate problemas em [Issues](https://github.com/kaueajure/ajrconnect/issues),
informando sistema, versões, monitor e passos para reproduzir.
Não inclua senhas ou dados pessoais de registros e capturas.

## Licença

Apache 2.0. Consulte [LICENSE](LICENSE) e
[avisos de terceiros](implementacao/distribution/NOTICE.txt).
Os avisos originais do FreeRDP são preservados nos fontes.
