---
title: AJR Connect
---

# AJR Connect

Cliente RDP para Linux, sem bloqueio por distribuição ou tipo de sessão.

## Instalar a versão de teste

No terminal da sessão gráfica, execute:

```bash
curl -fsSL https://kaueajure.github.io/ajrconnect/install.sh | bash
```

O comando baixa a versão de teste, verifica a integridade e executa o
instalador por usuário. Ele instala as dependências ausentes usando APT e
pode solicitar a senha de administrador apenas nessa etapa.
Configurações existentes são preservadas.
Abra AJR Connect pelo menu. Se a AJR Bar for instalada, saia da sessão e entre novamente.

[Código-fonte e instruções](https://github.com/kaueajure/ajrconnect) ·
[Versão de teste](https://github.com/kaueajure/ajrconnect/releases/tag/v6.0.0-beta.3)

Apache 2.0. A validação em um Zorin recém-instalado ainda está pendente.

O binário é Linux x86_64 e requer GTK4/libadwaita e FreeRDP/WinPR 2.11.5.
A AJR Bar é opcional para GNOME 46; outros desktops usam os controles do aplicativo.
