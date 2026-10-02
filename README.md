# AJR Connect — versão de teste

Cliente RDP com interface GTK4/libadwaita, frontend FreeRDP personalizado e
AJR Bar para controlar sessões Windows no GNOME 46.

Versão de teste: **6.0.0-beta.1**. A instalação em um Zorin recém-instalado
ainda precisa ser validada.

## Ambiente suportado

Zorin OS 18.1, Linux x86_64, GNOME 46, Wayland/XWayland e bibliotecas
FreeRDP/WinPR 2.11.5. O instalador verifica esses requisitos antes de alterar
arquivos e configurações. Outros ambientes ainda não foram validados.

O AJR Connect conecta a servidores Windows por RDP, incluindo VMs hospedadas
em Docker. Docker não é necessário no computador que executa o cliente.

## Download e instalação

Os comandos abaixo usam os arquivos da versão `v6.0.0-beta.1` em
[GitHub Releases](https://github.com/kaueajure/ajrconnect/releases).
Execute no terminal da sessão gráfica:

```bash
mkdir -p ajr-connect-download
cd ajr-connect-download

curl -fL -o ajr-connect-6-linux-x86_64.tar.gz \
  https://github.com/kaueajure/ajrconnect/releases/download/v6.0.0-beta.1/ajr-connect-6-linux-x86_64.tar.gz
curl -fL -o SHA256SUMS \
  https://github.com/kaueajure/ajrconnect/releases/download/v6.0.0-beta.1/SHA256SUMS

sha256sum --ignore-missing -c SHA256SUMS
tar -xzf ajr-connect-6-linux-x86_64.tar.gz
cd ajr-connect
python3 install.py --check
python3 install.py
```

Prossiga para extração e instalação somente se os downloads e a verificação
de integridade passarem. Execute o instalador **sem sudo**. Após instalar,
saia da sessão GNOME e entre novamente para carregar a AJR Bar.

Abra AJR Connect pelo menu de aplicativos. Configure servidor, usuário,
senha, monitor e pastas compartilhadas. Novas instalações começam com esses
campos vazios; configurações existentes são preservadas.

## Controles

- Ctrl+Alt+Enter alterna entre janela e fullscreen no monitor selecionado.
- Em fullscreen ativo, o teclado é capturado para encaminhar atalhos ao Windows.
- Em janela, os atalhos globais ficam com o Linux.
- No topo central da tela, a AJR Bar permite minimizar, sair de fullscreen e desconectar.

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

Os dez testes de compatibilidade, instalação e restauração passaram na
máquina de desenvolvimento, usando diretórios de usuário temporários e
configurações GNOME em memória. Os pacotes extraídos passaram na verificação
de compatibilidade e o cliente foi recompilado a partir dos fontes distribuídos.
O cliente também foi testado com uma VM real em dois monitores.

Essas verificações ainda não substituem um teste em uma instalação limpa do Zorin.
Relate problemas em [Issues](https://github.com/kaueajure/ajrconnect/issues),
informando sistema, versões, monitor e passos para reproduzir.
Não inclua senhas ou dados pessoais de registros e capturas.

## Licença

Apache 2.0. Consulte [LICENSE](LICENSE) e
[avisos de terceiros](implementacao/distribution/NOTICE.txt).
Os avisos originais do FreeRDP são preservados nos fontes.
