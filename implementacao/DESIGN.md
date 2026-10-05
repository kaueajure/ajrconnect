# Interface do AJR Connect

O cliente mantém GTK4/libadwaita e o frontend RDP existente. A identidade do
aplicativo é independente do tema visual da distribuição: grafite, violeta,
ícones vetoriais locais e uma hierarquia consistente de títulos, campos e ações.

## Responsabilidades

- `ajr_app.py`: perfis, credenciais, validação, conexão e controles da sessão.
- `core.py`: configuração, migração, persistência e montagem do comando RDP.
- `ui.py`: composição, navegação, barra lateral, busca, temas e resumos visuais.
- `dialogs.py`: editores de pasta e atalho; o seletor de pasta continua sendo GTK.
- `assets/style.css`: componentes visuais que usam as cores semânticas de `ui.py`.
- `assets/*.svg`: identidade e ilustração do espaço de trabalho, sem dependência de rede.

## Comportamento

Abaixo de 860 pixels, `Adw.OverlaySplitView` transforma a barra lateral em um
painel sobreposto. Um seletor de conexão aparece no conteúdo e o cabeçalho
oferece acesso à lista completa. A janela aceita largura mínima de 620 pixels.
O conteúdo rola verticalmente; estado, erros e ação de conexão ficam no rodapé.

O tema padrão é escuro. A escolha `appearance` é global, independente do perfil,
salva no JSON e preservada ao trocar de conexão. As configurações antigas não
precisam ser reescritas pelo instalador. Senhas continuam no chaveiro.

A navegação usa controles GTK com seleção explícita e nomes acessíveis.
Campos têm rótulos, foco visível e suporte nativo a colar senhas. Erros recebem
foco no rodapé. A animação curta da navegação respeita a preferência nativa
de animações do GTK. O cliente exibe apenas dados e estados reais da conexão.

Durante a conexão, a barra lateral e o seletor compacto ficam bloqueados com
o formulário, evitando mudar as credenciais da sessão em andamento. Falhas
de conexão restauram esses controles. A consulta de disponibilidade aguarda
250 ms após a última alteração do servidor antes de iniciar a chamada de rede.

## Verificação

`test_preferences.py` cobre a navegação, busca, painel compacto, temas, perfis,
credenciais, pastas e recuperação após falha de conexão em um HOME e Xvfb privados.
`test_distribution.py` verifica a cópia dos módulos, estilos e ícones e a
restauração. `check_desktop_ui.py --output ../previews` captura o aplicativo
real com dados de exemplo, em ambos os temas e em tamanhos diferentes.

Novos arquivos de interface precisam constar no instalador, em `package.py`,
na verificação de compatibilidade e na lista permitida do `.gitignore`.
