# Interface do AJR Connect

O cliente mantém GTK4/libadwaita e o frontend RDP existente. A identidade do
aplicativo é independente do tema visual da distribuição: grafite, violeta,
ícones vetoriais locais e uma hierarquia consistente de títulos, campos e ações.

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
- `assets/*.svg`: identidade e ilustração do espaço de trabalho, sem dependência de rede.

## Comportamento

Abaixo de 860 pixels, `Adw.OverlaySplitView` transforma a barra lateral em um
painel sobreposto. Um seletor de conexão aparece no conteúdo e o cabeçalho
oferece acesso à lista completa. A janela aceita largura mínima de 620 pixels.
O conteúdo rola verticalmente; estado, erros e ação de conexão ficam no rodapé.
A navegação entre Conexão, Tela e teclado e Compartilhamento fica em uma barra
superior de altura estável, fora da rolagem. O cartão da conexão rola junto
com os dados de acesso. Cada área mantém sua própria posição de rolagem.
Os controles de tela cheia, janela e minimizar também ficam no rodapé fixo.
Os textos identificam campos, ações e estados ou explicam configurações;
não há slogans nem cabeçalhos decorativos acima das áreas.

O tema padrão é escuro. A escolha `appearance` é global, independente do perfil,
salva no JSON e preservada ao trocar de conexão. As configurações antigas não
precisam ser reescritas pelo instalador. Senhas continuam no chaveiro.

A navegação usa controles GTK com seleção explícita e nomes acessíveis.
Campos têm rótulos, foco visível e suporte nativo a colar senhas. Erros recebem
foco no rodapé. A animação curta da navegação respeita a preferência nativa
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
o tema e exibir um erro, em tamanhos de janela amplo e compacto.
As regras de teclado têm testes de isolamento por perfil, conflitos, edição,
remoção e persistência. `check_keyboard_policy.py` exercita o cliente nativo
com teclas reais do frontend em um servidor X privado. `check_live_update.py`
verifica a execução local de uma combinação de área de trabalho no GNOME 46,
recusa por token inválido e ausência de associação, além da atualização da barra.
`test_distribution.py` verifica a cópia dos módulos, estilos e ícones e a
restauração. `check_desktop_ui.py --output ../previews` captura o aplicativo
real com dados de exemplo, em ambos os temas e em tamanhos diferentes.
`test_reconnect.py` simula quedas, recuperação, cancelamento e esgotamento das
tentativas no controlador GTK. `test_updates.py` verifica versões, integridade,
extração, cancelamento, progresso, reinício e instalação/restauração em um HOME
privado, sem substituir o aplicativo ou acessar o chaveiro do usuário.

Novos arquivos de interface precisam constar no instalador, em `package.py`,
na verificação de compatibilidade e na lista permitida do `.gitignore`.
