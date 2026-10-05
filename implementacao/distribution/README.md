# AJR Connect 6

Versão de teste: **6.0.0-beta.5**.

Cliente RDP com interface GTK4/libadwaita e barra de controles para GNOME 46.

## Requisitos de execução

O instalador não bloqueia por distribuição, versão do GNOME, X11 ou Wayland.
O binário fornecido é Linux x86_64 e requer GTK4/libadwaita, PyGObject,
bibliotecas X11 e FreeRDP/WinPR 2.11.5. A AJR Bar é opcional e compatível
com GNOME 46; em outros desktops, use os controles da janela do aplicativo.
Antes de instalar dependências, o instalador verifica se o binário corresponde
à arquitetura do sistema. Antes de copiar o aplicativo, verifica também as
bibliotecas vinculadas ao cliente, incluindo glibc, com `ldd`.
Para outra arquitetura ou um sistema com bibliotecas mais antigas, compile
os fontes no destino com as dependências de desenvolvimento necessárias.
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
O instalador usa as listas de pacotes existentes e não executa `apt-get update`.
O modo `--check` apenas verifica e não instala pacotes.
São necessários Python 3, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1,
x11-xserver-utils, libsecret-tools,
libfreerdp2-2t64, libfreerdp-client2-2t64 e libwinpr2-2t64
(ou os nomes equivalentes sem `t64`). Em distribuições sem APT, as
dependências devem ser instaladas pelo gerenciador do sistema.
As três bibliotecas RDP devem estar na versão 2.11.5; o cliente também
depende das bibliotecas X11 e demais bibliotecas resolvidas pelo sistema.

Se o APT falhar com `NO_PUBKEY`, corrija a chave/configuração do repositório
indicado conforme o fornecedor ou desative essa fonte se não a utiliza.
Para `deb.anydesk.com`, consulte https://deb.anydesk.com/howto.html.
Se as listas de pacotes estiverem desatualizadas, execute `sudo apt-get update`
manualmente após corrigir a fonte e repita a instalação.
Um aviso sobre repositório sem suporte a `i386` não significa que este
computador seja incompatível. O instalador preserva o diagnóstico do APT
e interrompe a instalação sem alterar as fontes ou ignorar assinaturas.

O aplicativo atualizado pode ser usado após fechar e abrir o AJR Connect e
reconectar o Windows. Atualizações da barra são aplicadas na sessão atual.
Na primeira instalação ou na migração da extensão antiga, um único novo login
pode ser necessário para ativar a ponte recarregável. O instalador informa esse caso.
Abra AJR Connect pelo menu de aplicativos. Informe servidor, usuário, senha,
monitor e, se desejar, pastas compartilhadas. As novas instalações começam
sem servidor, usuário ou pastas configurados.

Em **Conexão**, use **Nova** e **Salvar** para cadastrar vários servidores e
usuários. Cada perfil salva suas pastas, monitor e preferências. Ative
**Lembrar senha** para salvar também a senha no chaveiro, identificada pelo
servidor e usuário. A configuração anterior é preservada e convertida em perfil.
Selecione um perfil em **Conexões salvas**; use **Excluir** para removê-lo.
Perfis do mesmo servidor e usuário compartilham a credencial no chaveiro.

O botão de pasta abre um seletor GTK para navegar pelos diretórios locais.
Pastas de rede precisam estar montadas no Linux antes do compartilhamento.

Ctrl+Alt+Enter é o atalho inicial de tela cheia. Em **Tela e teclado**, clique
em **Alterar** no atalho, pressione a combinação desejada e salve.
Em **Prioridade dos atalhos**, escolha encaminhar teclas ao Windows somente
em tela cheia, também em janela ou manter atalhos no computador local.
Os interruptores de **Alt+Tab**, **Windows/Super** (sozinha) e **Alt+F4**
definem o destino individual: ativado para Windows, desativado para Linux.
Prioridades individuais exigem AJR Bar atualizada e ativa no GNOME 46; sem essa integração,
use todos no Windows ou mantenha os atalhos no computador local.
Super+R e outras combinações com Super seguem a captura geral. Atalhos
reservados pelo desktop podem ter prioridade quando a captura está desativada.
Reconecte depois de mudar as preferências de teclado.

Passe o mouse no topo central para minimizar, sair de fullscreen ou
desconectar pela AJR Bar.
Reconecte depois de alterar resolução ou escala dos monitores.

O aplicativo é instalado em `~/.local/share/ajr-connect/app`, o launcher em
`~/.local/bin/ajr-connect` e o atalho no menu em
`~/.local/share/applications/ajr-connect.desktop`.
A configuração fica em `~/.config/ajr-connect/config.json`. Senhas lembradas
ficam no chaveiro GNOME. A instalação preserva configurações existentes e
cria um backup dos componentes substituídos e das configurações GNOME afetadas.
Remove somente o atalho GNOME Ctrl+Alt+Enter que conflita com o cliente.

Para atualizar, desconecte a sessão Windows, feche o aplicativo e execute
novamente o instalador do pacote novo. Não precisa desinstalar. A barra usa uma
ponte fixa e módulos recarregáveis, permitindo atualizar seu funcionamento sem
reiniciar o desktop. Alterações excepcionais na ponte fixa ainda podem exigir
uma nova entrada na sessão. Atualizações não encerram sessões RDP abertas.

## Restaurar

No diretório extraído do pacote:

```sh
python3 rollback.py
```

Isso restaura o backup mais recente. Backups com a ponte recarregável podem
reativar a barra na mesma sessão. Backups da extensão antiga ainda podem exigir
uma nova entrada na sessão; o comando informa o resultado.

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
