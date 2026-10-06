---
title: AJR Connect
---

# AJR Connect

Cliente RDP para Linux, sem bloqueio por distribuição ou tipo de sessão.

## Instalar a versão de teste

Versão atual: **6.0.0-beta.9**.

No terminal da sessão gráfica, execute:

```bash
curl -fsSL https://kaueajure.github.io/ajrconnect/install.sh | bash
```

O comando baixa a versão de teste, verifica a integridade e executa o
instalador por usuário. Ele instala as dependências ausentes usando APT e
pode solicitar a senha de administrador apenas nessa etapa.
Usa as listas de pacotes existentes, sem executar `apt-get update`.
Configurações existentes são preservadas.
Abra AJR Connect pelo menu. Para atualizar, execute novamente o mesmo comando,
feche e abra o aplicativo e reconecte ao Windows. A AJR Bar pode ser atualizada
na sessão atual. A barra agora é integrada ao cliente RDP e dispensa novo login,
inclusive ao migrar a versão antiga. Para os atalhos locais, autorize o teclado
quando o sistema solicitar e marque a opção de lembrar essa autorização.

Esta versão inclui a interface V2 com superfícies neutras e accent violeta, temas claro e escuro,
conexões salvas com busca, seleção de pastas pelo botão,
atalho de tela cheia personalizável e prioridade configurável de Alt+Tab,
Windows/Super e Alt+F4. Para atalhos locais, o portal do sistema solicita
autorização de teclado quando a integração GNOME não está disponível.
Inclui atualização pelo aplicativo e reconexão automática após quedas de rede.
Em versões com atualização integrada, abra **Mais opções → Atualizações**,
ative **Incluir versões de teste**, verifique e instale a nova versão.

[Código-fonte e instruções](https://github.com/kaueajure/ajrconnect) ·
[Versão de teste](https://github.com/kaueajure/ajrconnect/releases/tag/v6.0.0-beta.9)

Apache 2.0. A validação em um Zorin recém-instalado ainda está pendente.

O binário é Linux x86_64 e requer GTK4/libadwaita e FreeRDP/WinPR 2.11.5.
A AJR Bar é integrada ao cliente RDP e dispensa a extensão GNOME.
A integração opcional com GNOME 46 ou o portal do sistema executa os atalhos locais.
