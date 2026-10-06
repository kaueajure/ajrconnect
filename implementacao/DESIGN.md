# Interface V2 do AJR Connect

O cliente mantém GTK4/libadwaita e o frontend RDP existente. A identidade do
aplicativo usa superfícies neutras, violeta como accent, ícones simbólicos GTK
e uma hierarquia consistente de títulos, campos e ações. O hero e a ilustração
de monitor foram removidos; não há cards envolvendo outros grupos de preferências.

## Responsabilidades

- `ajr_app.py`: perfis, credenciais, validação, conexão e controles da sessão.
- `core.py`: configuração, migração, persistência e montagem do comando RDP.
- `ui.py`: composição, navegação, barra lateral, busca, temas e resumos visuais.
- `dialogs.py`: editores de pasta e atalho; o seletor de pasta continua sendo GTK.
- `keyboard.py`: combinações, sugestões, conflitos e protocolo de regras de teclado.
- `reconnect.py`: política de tentativas de recuperação por falhas de rede.
- `updates.py`: consulta de versões, download verificado e aplicação da atualização.
- `update_dialog.py`: progresso, cancelamento e reinício do aplicativo após atualização.
- `version.py`: versão única usada pelo aplicativo e pela preparação de publicação.
- `assets/style.css`: componentes visuais que usam as cores semânticas de `ui.py`.
- `assets/ajr-connect.svg`: ícone do aplicativo, sem dependência de rede.
  `workspace.svg` permanece no pacote por compatibilidade, mas não é usado pela V2.

## Comportamento

Abaixo de 860 pixels, `Adw.OverlaySplitView` transforma a barra lateral em um
painel sobreposto. Um seletor de conexão aparece no conteúdo e o cabeçalho
oferece acesso à lista completa. Até 560 pixels de altura no modo compacto,
o seletor duplicado sai do conteúdo e a lista continua acessível pela sidebar.
Até 1040 pixels de largura, os campos de acesso empilham verticalmente;
em janelas maiores ficam em duas colunas. A janela aceita 620 × 480 pixels.
O conteúdo rola verticalmente; estado, erros e ação de conexão ficam no rodapé.
A navegação entre Conexão, Tela e teclado e Compartilhamento fica em uma barra
superior de altura estável, com o nome e a identidade da conexão selecionada,
fora da rolagem. Cada área mantém sua própria posição de rolagem.
O rodapé apresenta status, Salvar e Conectar quando desconectado. Durante uma
sessão, Salvar sai e aparecem Desconectar e os controles de tela cheia, janela
e minimizar. Reconexões mostram spinner, próxima tentativa e cancelamento.
Os textos identificam campos, ações e estados ou explicam configurações;
não há slogans nem cabeçalhos decorativos acima das áreas.

O tema padrão é escuro. A escolha `appearance` é global, independente do perfil,
salva no JSON e preservada ao trocar de conexão. As configurações antigas não
precisam ser reescritas pelo instalador. Senhas continuam no chaveiro.

A navegação usa controles GTK com seleção explícita e nomes acessíveis.
Campos têm rótulos, foco visível e suporte nativo a colar senhas. Erros recebem
foco no rodapé e permitem copiar a mensagem. A animação curta da navegação respeita a preferência nativa
de animações do GTK. O cliente exibe apenas dados e estados reais da conexão.

As regras adicionais de teclado são salvas em cada perfil. O editor aceita
gravação, texto e sugestões, com destino explícito. Combinações duplicadas e
conflitos com o atalho de tela cheia são rejeitados. Regras locais aguardam a
liberação das teclas físicas antes de executar a combinação na AJR Bar; ela
usa as associações existentes do GNOME e rejeita atalhos não configurados.
O cliente consome a reprodução local até receber confirmação, evitando enviar
a mesma combinação ao Windows. Sem captura, prevalecem os atalhos do desktop.

Durante a conexão, a barra lateral e o seletor compacto ficam bloqueados com
o formulário, evitando mudar as credenciais da sessão em andamento. Falhas
de conexão restauram esses controles. A consulta de disponibilidade aguarda
250 ms após a última alteração do servidor antes de iniciar a chamada de rede.

A reconexão automática é uma preferência de cada conexão. Depois de uma sessão
estabelecida cair por falha de rede, o controlador tenta novamente após 2, 4, 8,
16 e 30 segundos. O rodapé mostra a espera e permite cancelar inclusive durante
a abertura da sessão. Erros de autenticação e encerramentos voluntários não
iniciam tentativas. A senha usada fica somente em memória enquanto a sessão
ou suas tentativas estiverem ativas, independentemente da opção de chaveiro.

As preferências de atualização são globais. A consulta pública de versões e o
download acontecem em threads, com progresso encaminhado ao GTK. Apenas a
instalação por usuário pode ser substituída; os fontes de desenvolvimento ficam
protegidos. Antes de instalar, o cliente confere tamanho, SHA256, entradas do
arquivo e identidade da versão. A instalação usa backup e um registro para
restauração após falhas. O reinício fecha o processo anterior antes de abrir o
novo. A atualização exige encerrar a conexão e não altera suas configurações.

## Verificação

`test_preferences.py` cobre a navegação, busca, painel compacto, temas, perfis,
credenciais, pastas e recuperação após falha de conexão em um HOME e Xvfb privados.
O teste compara as coordenadas reais dos botões ao trocar de área, rolar, mudar
o tema e exibir um erro, em tamanhos de janela amplo e compacto. A regressão
V2 também verifica empilhamento e restauração dos campos, títulos longos,
620 × 480, ações do menu, Enter na senha, Salvar, estado vazio, menus das pastas
e atualização do destino das regras.
As regras de teclado têm testes de isolamento por perfil, conflitos, edição,
remoção e persistência. `check_keyboard_policy.py` exercita o cliente nativo
com teclas reais do frontend em um servidor X privado. `check_live_update.py`
verifica a execução local de uma combinação de área de trabalho no GNOME 46,
recusa por token inválido e ausência de associação, além da atualização da barra.
`test_distribution.py` verifica a cópia dos módulos, estilos e ícones e a
restauração. `check_desktop_ui.py --output ../previews` captura o aplicativo
real com dados de exemplo, em ambos os temas e em 1120 × 820, 680 × 760 e
620 × 480. Além das dez capturas originais, inclui pastas com caminhos longos,
editor de pastas, erros, foco da senha e controles de sessão. Confere as
alocações reais para detectar overflow horizontal e ações fixas ocultas.
`test_reconnect.py` simula quedas, recuperação, cancelamento e esgotamento das
tentativas no controlador GTK. `test_updates.py` verifica versões, integridade,
extração, cancelamento, progresso, reinício e instalação/restauração em um HOME
privado, sem substituir o aplicativo ou acessar o chaveiro do usuário.

Novos arquivos de interface precisam constar no instalador, em `package.py`,
na verificação de compatibilidade e na lista permitida do `.gitignore`.

## Validação da V2 — 6 de outubro de 2026

Executados em `implementacao/`:

- `python3 -m unittest discover -s tests -p 'test_*.py' -v`: 70 testes aprovados,
  incluindo os 69 anteriores e a nova regressão de apresentação V2.
- `python3 tests/check_keyboard_policy.py`: aprovado; regras locais/remotas,
  captura, modificadores, foco, recuperação e atalho de fullscreen.
- `python3 tests/check_live_update.py`: aprovado no GNOME 46; integração local,
  validação de token, atualização e rollback com o mesmo processo do Shell.
- `python3 tests/check_desktop_ui.py --output ../previews`: aprovado;
  31 capturas finais, sem overflow horizontal ou ações fixas ocultas.

As capturas foram revisadas durante as etapas e após os ajustes de contraste,
altura dos diálogos, estado vazio, rodapé, foco de erros e janela mínima.
Nos painéis roláveis, conteúdo maior que a janela continua acessível pela
rolagem; navegação e ações permanecem fora dela. O botão primário escuro usa
contraste de 4,72:1 com texto branco. As capturas usam renderização Cairo/Xvfb;
os avisos de EGL e ausência de barramento D-Bus são esperados nesse ambiente.

A validação usa perfis de exemplo e HOME privado, sem consultar credenciais
do usuário nem abrir uma sessão RDP real. Os módulos de sessão, FreeRDP,
armazenamento, chaveiro e atualização mantêm sua lógica anterior.
