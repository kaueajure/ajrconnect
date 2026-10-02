# AJR Connect 6

Cliente RDP com interface GTK4/libadwaita e barra de controles para GNOME 46.

## Requisitos de execução

O instalador não bloqueia por distribuição, versão do GNOME, X11 ou Wayland.
O binário fornecido é Linux x86_64 e requer GTK4/libadwaita, PyGObject,
bibliotecas X11 e FreeRDP/WinPR 2.11.5. A AJR Bar é opcional e compatível
com GNOME 46; em outros desktops, use os controles da janela do aplicativo.
O aplicativo conecta a servidores Windows com RDP disponível, incluindo VMs
hospedadas em Docker; Docker não é necessário no computador do cliente.

## Instalação

Extraia o pacote, entre no diretório `ajr-connect` e execute no terminal da
seu usuário, sem sudo:

```sh
python3 install.py --check
python3 install.py
```

A verificação lista somente os componentes e dependências necessários para executar o cliente. No modo de instalação, as dependências
ausentes são instaladas pelos repositórios do sistema. A senha de administrador
pode ser solicitada apenas nessa etapa. O aplicativo é instalado por usuário.
O modo `--check` apenas verifica e não instala pacotes.
São necessários Python 3, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1,
x11-xserver-utils, libsecret-tools,
libfreerdp2-2t64, libfreerdp-client2-2t64 e libwinpr2-2t64
(ou os nomes equivalentes sem `t64`). Em distribuições sem APT, as
dependências devem ser instaladas pelo gerenciador do sistema.
As três bibliotecas RDP devem estar na versão 2.11.5; o cliente também
depende das bibliotecas X11 e demais bibliotecas resolvidas pelo sistema.

Se a AJR Bar for instalada, saia da sessão e entre novamente para carregá-la.
Abra AJR Connect pelo menu de aplicativos. Informe servidor, usuário, senha,
monitor e, se desejar, pastas compartilhadas. As novas instalações começam
sem servidor, usuário ou pastas configurados.

Em janela, os atalhos globais ficam com o Linux. Em fullscreen ativo, o
cliente captura o teclado para encaminhar os atalhos ao Windows.
Ctrl+Alt+Enter alterna fullscreen no monitor selecionado. Passe o mouse no
topo central para minimizar, sair de fullscreen ou desconectar pela AJR Bar.
Reconecte depois de alterar resolução ou escala dos monitores.

O aplicativo é instalado em `~/.local/share/ajr-connect/app`, o launcher em
`~/.local/bin/ajr-connect` e o atalho no menu em
`~/.local/share/applications/ajr-connect.desktop`.
A configuração fica em `~/.config/ajr-connect/config.json`. Senhas lembradas
ficam no chaveiro GNOME. A instalação preserva configurações existentes e
cria um backup dos componentes substituídos e das configurações GNOME afetadas.
Remove somente o atalho GNOME Ctrl+Alt+Enter que conflita com o cliente.

## Restaurar

No diretório extraído do pacote:

```sh
python3 rollback.py
```

Isso restaura o backup mais recente e requer sair e entrar na sessão.

## Integridade, fontes e licenças

Os arquivos SHA256SUMS permitem verificar se o download corresponde ao
pacote publicado. Para conferir os dois arquivos baixados:

```sh
sha256sum -c SHA256SUMS
```

Hashes não substituem a verificação da origem do download.
O arquivo `ajr-connect-6-sources.tar.gz` contém os fontes correspondentes,
o frontend FreeRDP modificado, os cabeçalhos e o script de compilação.
O frontend usa bibliotecas do sistema; elas não são incluídas no pacote.
Leia `NOTICE.txt` e os arquivos em `licenses/` para o estado das licenças.
