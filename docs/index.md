---
title: AJR Connect
---

# AJR Connect

Cliente RDP para Linux, sem bloqueio por distribuição ou tipo de sessão.

## Instalar a versão de teste

Versão atual: **6.0.0-beta.8**.

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
na sessão atual. A primeira instalação ou a migração da extensão antiga pode
exigir um único novo login; o instalador informa quando isso for necessário.

Esta versão inclui a interface V2 com superfícies neutras e accent violeta, temas claro e escuro,
conexões salvas com busca, seleção de pastas pelo botão,
atalho de tela cheia personalizável e prioridade configurável de Alt+Tab,
Windows/Super e Alt+F4. As prioridades individuais exigem AJR Bar ativa no GNOME 46.
Inclui atualização pelo aplicativo e reconexão automática após quedas de rede.
Em versões com atualização integrada, abra **Mais opções → Atualizações**,
ative **Incluir versões de teste**, verifique e instale a nova versão.

[Código-fonte e instruções](https://github.com/kaueajure/ajrconnect) ·
[Versão de teste](https://github.com/kaueajure/ajrconnect/releases/tag/v6.0.0-beta.8)

Apache 2.0. A validação em um Zorin recém-instalado ainda está pendente.

O binário é Linux x86_64 e requer GTK4/libadwaita e FreeRDP/WinPR 2.11.5.
A AJR Bar é opcional para GNOME 46; outros desktops usam os controles do aplicativo.
