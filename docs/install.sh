#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# AJR Connect one-command installer. The application installer creates backups.

AJR_INSTALL_TMP=''

ajr_cleanup() {
    if [[ -n "$AJR_INSTALL_TMP" ]]; then
        rm -rf -- "$AJR_INSTALL_TMP"
    fi
}

ajr_apt() {
    local output status
    if output=$(sudo apt-get "$@" 2>&1); then
        status=0
    else
        status=$?
    fi
    if [[ "$status" != '0' || "$output" == *NO_PUBKEY* || "$output" == *EXPKEYSIG* || "$output" == *BADSIG* || "$output" == *'not signed'* ]]; then
        printf '%s\n' "$output" >&2
        printf 'Falha ao executar sudo apt-get (código %s).\n' "$status" >&2
        if [[ "$output" == *NO_PUBKEY* || "$output" == *EXPKEYSIG* || "$output" == *BADSIG* || "$output" == *'not signed'* ]]; then
            printf 'O APT bloqueou um repositório por falha de assinatura/chave GPG. Corrija a fonte conforme o fornecedor ou desative-a se não a utiliza.\n' >&2
            if [[ "$output" == *deb.anydesk.com* ]]; then
                printf 'AnyDesk: https://deb.anydesk.com/howto.html\n' >&2
            fi
        fi
        printf 'Se as listas de pacotes estiverem desatualizadas, corrija eventuais falhas de repositório e execute sudo apt-get update manualmente antes de tentar novamente.\n' >&2
        if [[ "$status" == '0' ]]; then status=1; fi
        return "$status"
    fi
    printf '%s\n' "$output"
}

ajr_main() {
    set -euo pipefail
    local mode="${1:-}" tool
    local version='v6.0.0-beta.6'
    local asset='ajr-connect-6-linux-x86_64.tar.gz'
    local expected='22c8cf1195569dfe31d6acf627ac99e41d1965d2a78a22041d61e4ed6253b410'
    local base_url="https://github.com/kaueajure/ajrconnect/releases/download/$version"

    case "$mode" in
        --help|-h)
            printf 'AJR Connect: instala a versão de teste por usuário.\n'
            printf 'Opções: --check (apenas verificar), --help.\n'
            return 0
            ;;
        ''|--check) ;;
        *) printf 'Opção desconhecida: %s\n' "$mode" >&2; return 1 ;;
    esac
    if [[ $# -gt 1 ]]; then
        printf 'Informe no máximo uma opção: --check ou --help.\n' >&2
        return 1
    fi
    if [[ "$(id -u)" == '0' ]]; then
        printf 'Execute com seu usuário, sem sudo.\n' >&2
        return 1
    fi
    if [[ "$(uname -s)" != 'Linux' || "$(uname -m)" != 'x86_64' ]]; then
        printf 'Este download contém um cliente Linux x86_64. Sistema detectado: %s %s.\n' "$(uname -s)" "$(uname -m)" >&2
        printf 'Para outra arquitetura, baixe os fontes e compile com python3 native/build.py.\n' >&2
        return 1
    fi
    for tool in curl tar sha256sum mktemp; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            printf 'Dependência ausente: %s. Instale-a e execute novamente.\n' "$tool" >&2
            return 1
        fi
    done

    AJR_INSTALL_TMP=$(mktemp -d "${TMPDIR:-/tmp}/ajr-connect.XXXXXXXX")
    trap ajr_cleanup EXIT
    printf 'AJR Connect %s — baixando instalador…\n' "$version"
    curl -fsSL --retry 3 --connect-timeout 15 --max-time 120 \
        "$base_url/$asset" -o "$AJR_INSTALL_TMP/$asset"
    if ! printf '%s  %s\n' "$expected" "$AJR_INSTALL_TMP/$asset" | sha256sum --check --status; then
        printf 'O arquivo baixado falhou na verificação de integridade. Instalação cancelada.\n' >&2
        return 1
    fi
    printf 'Integridade confirmada. Preparando a instalação…\n'
    tar -xzf "$AJR_INSTALL_TMP/$asset" -C "$AJR_INSTALL_TMP"
    if ! command -v python3 >/dev/null 2>&1; then
        if [[ "$mode" == '--check' ]]; then
            printf 'Dependência ausente: python3. O modo --check não instala pacotes.\n' >&2
            return 1
        fi
        if ! command -v apt-get >/dev/null 2>&1; then
            printf 'Instale Python 3 com o gerenciador da sua distribuição e execute novamente.\n' >&2
            return 1
        fi
        printf 'Instalando Python 3; será solicitada a senha de administrador.\n'
        sudo -v
        ajr_apt --yes --no-remove --no-install-recommends install python3
    fi
    if [[ "$mode" == '--check' ]]; then
        python3 "$AJR_INSTALL_TMP/ajr-connect/install.py" --check
    else
        python3 "$AJR_INSTALL_TMP/ajr-connect/install.py"
    fi
}

# Keep invocation last: a truncated download cannot call the installer.
ajr_main "$@"
