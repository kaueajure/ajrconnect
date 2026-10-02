#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# AJR Connect one-command installer. The application installer creates backups.

AJR_INSTALL_TMP=''

ajr_cleanup() {
    if [[ -n "$AJR_INSTALL_TMP" ]]; then
        rm -rf -- "$AJR_INSTALL_TMP"
    fi
}

ajr_main() {
    set -euo pipefail
    local mode="${1:-}" tool
    local version='v6.0.0-beta.2'
    local asset='ajr-connect-6-linux-x86_64.tar.gz'
    local expected='d772c3ce6b5291ac4de04507332cf481e039fcb384071f78b483edf8bc6e9061'
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
        printf 'Execute na sessão gráfica do seu usuário, sem sudo.\n' >&2
        return 1
    fi
    if [[ "$(uname -s)" != 'Linux' || "$(uname -m)" != 'x86_64' ]]; then
        printf 'Esta versão requer Linux x86_64 com Zorin OS 18.1.\n' >&2
        return 1
    fi
    if [[ "${XDG_SESSION_TYPE:-}" != 'wayland' || -z "${DISPLAY:-}" || -z "${WAYLAND_DISPLAY:-}" ]]; then
        printf 'Execute em um terminal da sessão GNOME Wayland com XWayland disponível.\n' >&2
        return 1
    fi
    # Verify the supported OS before any privileged operation, even without Python.
    local os_key os_value os_id='' os_version=''
    while IFS='=' read -r os_key os_value; do
        os_value=${os_value#\"}; os_value=${os_value%\"}
        case "$os_key" in
            ID) os_id=$os_value ;;
            VERSION) os_version=$os_value ;;
        esac
    done < /etc/os-release
    if [[ "$os_id" != 'zorin' || "$os_version" != '18.1' ]]; then
        printf 'Esta versão requer Zorin OS 18.1.\n' >&2
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
    printf 'Integridade confirmada. Verificando o ambiente…\n'
    tar -xzf "$AJR_INSTALL_TMP/$asset" -C "$AJR_INSTALL_TMP"
    if ! command -v python3 >/dev/null 2>&1; then
        if [[ "$mode" == '--check' ]]; then
            printf 'Dependência ausente: python3. O modo --check não instala pacotes.\n' >&2
            return 1
        fi
        if [[ ":${XDG_CURRENT_DESKTOP:-}:" != *':GNOME:'* ]] \
                || ! command -v gnome-shell >/dev/null 2>&1 \
                || [[ "$(gnome-shell --version)" != 'GNOME Shell 46.'* ]]; then
            printf 'Esta versão requer a sessão GNOME 46.\n' >&2
            return 1
        fi
        printf 'Instalando Python 3; será solicitada a senha de administrador.\n'
        sudo -v
        sudo apt-get update
        sudo apt-get --yes --no-remove --no-install-recommends install python3
    fi
    if [[ "$mode" == '--check' ]]; then
        python3 "$AJR_INSTALL_TMP/ajr-connect/install.py" --check
    else
        python3 "$AJR_INSTALL_TMP/ajr-connect/install.py"
    fi
}

# Keep invocation last: a truncated download cannot call the installer.
ajr_main "$@"
