# AJR Connect — versão de teste

Cliente RDP com interface GTK4/libadwaita, frontend FreeRDP personalizado e
AJR Bar integrada ao cliente para controlar sessões Windows.

Versão de teste: **6.0.0-beta.9**. Inclui a interface V2, atualização pelo
aplicativo, reconexão automática, conexões salvas, seleção de pastas,
atalhos personalizáveis e atualização da AJR Bar na sessão atual.
A instalação em um Zorin recém-instalado
ainda precisa ser validada.

## Interface V2

A interface usa superfícies neutras e violeta como accent, temas claro/escuro, conexões com busca
na barra lateral e áreas separadas para conexão, tela/teclado e compartilhamento.
O tema escolhido é preservado e vale para todas as conexões. Em janelas menores,
a lista de conexões fica em um painel acessível pelo botão do cabeçalho.
Os campos empilham em janelas menores, os controles de sessão aparecem quando
necessários e o estado vazio de compartilhamento oferece a ação de adicionar pasta.

Para atualizar a partir de uma versão com atualização integrada, abra
**Mais opções → Atualizações**, mantenha **Incluir versões de teste** ativado
e escolha **Verificar atualizações**. Depois de instalar, reinicie o aplicativo.
Em versões anteriores, execute novamente o comando de instalação abaixo.

A apresentação está em `implementacao/ui.py`, os editores de pasta e atalho em
`implementacao/dialogs.py` e os estilos e ícones em `implementacao/assets/`.
O controlador de perfis e sessões permanece em `implementacao/ajr_app.py`.

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

A AJR Bar pertence ao cliente RDP e não exige uma extensão GNOME.
Os controles também estão disponíveis na janela do aplicativo.
Use Ctrl+Alt+Enter para alternar a tela cheia.

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
O aplicativo atualizado pode ser usado após fechar e abrir o AJR Connect e
reconectar o Windows. Atualizações da AJR Bar são aplicadas na sessão atual.
A AJR Bar faz parte do cliente RDP e funciona após reabrir e reconectar, sem
encerrar a sessão Linux. Quando necessário, o sistema pede autorização de
teclado para os atalhos locais. Ative a opção de lembrar essa autorização.

Para apenas verificar o ambiente:

```bash
curl -fsSL https://kaueajure.github.io/ajrconnect/install.sh | bash -s -- --check
```

Abra AJR Connect pelo menu de aplicativos. Configure servidor, usuário,
senha, monitor e pastas compartilhadas. Novas instalações começam com esses
campos vazios; configurações existentes são preservadas.

## Controles

- Ctrl+Alt+Enter é o atalho inicial de tela cheia. Em **Tela e teclado → Atalho
  de tela cheia → Alterar**, pressione a combinação desejada e salve.
- Em **Atalhos**, escolha encaminhar atalhos ao Windows somente
  em tela cheia, também em janela ou manter os atalhos no computador local.
- Ative ou desative individualmente **Alt+Tab**, **Windows/Super** (sozinha) e
  **Alt+F4**. Ativado executa no Windows; desativado executa no Linux.
  Para essa combinação de prioridades, autorize o teclado no sistema quando solicitado.
- Em **Tela e teclado → Atalhos personalizados → Adicionar atalho**, escolha uma
  sugestão ou informe qualquer combinação, por exemplo **Ctrl + Alt + Esquerda**,
  **Super + Ctrl + Direita** ou **Super + D**. Escolha **Este computador** ou
  **Windows**. Depois, use os botões da regra para editar ou remover o atalho.
  Nas regras, ativado executa no Windows; desativado executa neste computador.
  As regras são salvas por conexão; combinações sem regra seguem a captura geral.
- Para executar um atalho local, ele precisa estar configurado nas opções de
  teclado do Linux. O aplicativo usa a ação existente, inclusive atalhos
  personalizados do sistema. É possível digitar a combinação quando o desktop
  a intercepta durante a gravação. Regras duplicadas ou que usem o atalho de
  tela cheia são rejeitadas.
- A AJR Bar no topo central da janela RDP permite minimizar, sair de fullscreen e desconectar.
- Os mesmos controles estão disponíveis na janela do aplicativo.

Atalhos que o desktop reserva podem ter prioridade quando a captura está
desativada. Escolha uma combinação livre para alternar tela cheia em janela.
Reconecte depois de alterar as opções de teclado.

## Conexões e pastas

Em **Conexão**, use **Nova**, preencha um nome, servidor, usuário e senha e
clique em **Salvar**. Selecione uma conexão em **Conexões salvas** para recuperar
seus dados. Cada perfil mantém monitor, pastas e preferências próprios. A conexão
da configuração antiga é convertida em perfil sem perder essas preferências.

Ative **Lembrar senha** antes de salvar para guardar a senha no chaveiro GNOME.
As senhas são identificadas por servidor e usuário e não entram no arquivo JSON.
Perfis que usam o mesmo servidor e usuário compartilham a mesma credencial.
**Excluir** solicita confirmação e remove a credencial se nenhum outro perfil
usa esse par de servidor e usuário.

Em **Adicionar pasta**, clique no ícone de pasta, navegue pelos diretórios do
Linux e escolha **Selecionar pasta**. O seletor GTK abre diretamente, sem
depender do portal de arquivos. Pastas de rede precisam estar montadas e
disponíveis como diretórios locais antes de serem compartilhadas.

## Atualizações sem sair da sessão

No aplicativo, abra **Mais opções → Atualizações** no cabeçalho. A janela mostra a
versão atual, procura versões publicadas e oferece **Baixar e atualizar**.
O download tem progresso e pode ser cancelado. O pacote é conferido por SHA256
antes de instalar, e uma falha de instalação tenta restaurar o backup anterior.
Depois, clique em **Reiniciar aplicativo**. As configurações e senhas do chaveiro
são preservadas. Desconecte do Windows antes de atualizar.

Você pode ativar **Verificar ao abrir o aplicativo** e escolher se deseja
incluir versões de teste. O aplicativo avisa quando há uma versão nova.
Ao executar os fontes localmente, a consulta funciona, mas a atualização é
feita pelo aplicativo instalado para preservar o diretório de desenvolvimento.

### Reconexão automática

Em **Conexão**, ative **Reconectar automaticamente**. A opção é salva por
conexão e começa ativada. Depois de uma sessão estabelecida, uma queda de rede
inicia até cinco tentativas, com esperas de 2, 4, 8, 16 e 30 segundos.
O rodapé mostra a próxima tentativa e oferece **Cancelar reconexão**.

A recuperação reutiliza os dados da sessão e o modo de tela. A senha permanece
apenas em memória durante a conexão e suas tentativas; não vai para JSON ou
registros. Erros de autenticação, logoff e encerramentos voluntários não
provocam reconexão. Se todas as tentativas falharem, os campos são liberados
para corrigir a configuração e conectar manualmente.

### Atualizar pelo terminal

Execute novamente o mesmo comando de instalação para baixar a versão nova.
Ele preserva as configurações,
faz backup e atualiza a barra pelo seu canal D-Bus. Não desativa a extensão a
cada instalação, não reinicia o GNOME Shell e não encerra as conexões RDP abertas.
Feche e abra o AJR Connect para carregar a nova interface e reconecte o Windows
para carregar o novo cliente RDP.

A extensão passa a ter uma parte fixa (`extension.js`) e módulos de integração
com nomes derivados do conteúdo. Isso permite importar o código novo sem
reutilizar a versão antiga guardada no cache do GNOME. Erros ao importar a nova
versão mantêm a barra anterior; erros ao ativá-la tentam restaurar a anterior.

A barra de controles agora está dentro da janela RDP e dispensa a extensão
GNOME, inclusive na primeira instalação e na migração da versão antiga.
A extensão recarregável continua como um backend opcional para os atalhos.
Quando ela está indisponível, o portal do desktop autoriza somente o teclado:
não solicita compartilhamento de tela, mouse ou área de transferência.
No GNOME 46, a opção de lembrar permite restaurar a autorização ao reabrir.
Se ela for recusada ou revogada, o aplicativo oferece **Autorizar** para repetir
a tentativa; os controles da barra continuam disponíveis.

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
python3 tests/check_keyboard_policy.py
python3 tests/check_live_update.py
python3 tests/check_desktop_ui.py --output ../previews
```

Os testes de interface e teclado usam Xvfb e não acessam a VM nem o chaveiro
real. Para instalar a partir dos fontes, execute `python3 install.py`
após compilar. O instalador informa se a integração foi aplicada na sessão atual
ou se esta instalação precisa da ativação inicial da ponte.

Para gerar os pacotes localmente, execute `python3 package.py` a partir de
`implementacao/`. Os arquivos são gerados em `dist/`, fora do controle de versão.

## Publicar uma nova versão

Subir o código não publica os pacotes instaláveis. Para cada versão:

1. Atualize `APP_VERSION` em `implementacao/version.py` e as versões nos READMEs. As notas de publicação usam essa mesma versão.
2. Gere os pacotes com `python3 implementacao/package.py` e execute os testes.
3. Gere as notas com `python3 implementacao/prepare_release.py --repo kaueajure/ajrconnect --output /tmp/ajr-publicacao-nova`. Use um diretório de saída que ainda não exista. Faça commit dos fontes correspondentes e envie para `main` antes de criar a Release.
4. No GitHub, abra **Releases → Draft a new release**, escolha uma tag nova e a branch `main`, cole as notas geradas e anexe os três arquivos de `dist/`: o pacote Linux, os fontes e `SHA256SUMS`. Para versões beta, marque **Pre-release** e publique.
5. Depois que os downloads estiverem disponíveis, atualize `version` e `expected` em `docs/install.sh`. O hash está em `dist/SHA256SUMS`, na linha do pacote Linux. Atualize também a versão e o link em `docs/index.md`, faça commit e envie para `main`.
6. Aguarde o GitHub Pages publicar e confira `curl -fsSL https://kaueajure.github.io/ajrconnect/install.sh | bash -s -- --check`.

O mesmo comando de instalação passa a atualizar os usuários para a versão nova,
preservando configurações. Não substitua os arquivos de uma Release antiga;
publique uma tag nova para cada atualização.
Consulte também as [instruções oficiais do GitHub](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).

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
