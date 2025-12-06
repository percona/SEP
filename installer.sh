#!/usr/bin/env bash

set -o errexit
set -o nounset

test "${DEBUG:-0}" = 0 || set -o xtrace

is_tty() {
    [ -t 1 ] && [ -r /dev/tty ] && [ -w /dev/tty ]
}

# Styles & Colors
COLOR_PRIMARY="212" # Pinkish
COLOR_SEC="99"      # Purple
COLOR_SUBTLE="240"  # Grey
COLOR_WARN="208"    # Orange

# State tracking
DIR_WAS_CREATED_BY_SCRIPT=0
TEMP_DIR=""
GUM_BIN_PATH=""

# Configuration
if [ -z "${NO_GUM:-}" ]; then
    is_tty && NO_GUM=0 || NO_GUM=1
fi
if [ -z "${NO_CLEAR:-}" ]; then
    [ "${DEBUG:-0}" -eq 0 ] && is_tty && NO_CLEAR=0 || NO_CLEAR=1
fi

################################################################################
# LOGGING HELPERS
################################################################################

log_info() {
    if [ "${NO_GUM}" -eq 0 ] && command -v gum > /dev/null 2>&1; then
        gum log --level info "$1"
    else
        echo "[INFO] $1"
    fi
}

log_err() {
    if [ "${NO_GUM}" -eq 0 ] && command -v gum > /dev/null 2>&1; then
        gum log --level error "$1"
    else
        echo "[ERROR] $1" >&2
    fi
}

log_warn() {
    if [ "${NO_GUM}" -eq 0 ] && command -v gum > /dev/null 2>&1; then
        gum log --level warn "$1"
    else
        echo "[WARN] $1" >&2
    fi
}

separator() {
    printf '\n%s\n' "------------------------------------------------------------"
}

clear_screen() {
    [ "${NO_CLEAR}" -eq 1 ] || ! is_tty && separator && return 0

    if command -v tput > /dev/null 2>&1; then
        tput clear && return 0
    fi

    if command -v clear > /dev/null 2>&1; then
        clear && return 0
    fi

    printf '\033[2J\033[H'
}

banner() {
    clear_screen
    if [ "${NO_GUM}" -eq 0 ] && command -v gum > /dev/null 2>&1; then
        gum style --border double --margin "1" --padding "1 2" --border-foreground "$COLOR_PRIMARY" \
            "SEP INSTALLER"
    else
        echo "================================================================================"
        echo "                                 SEP INSTALLER                                  "
        echo "================================================================================"
        echo ""
    fi
}

cleanup() {
    echo ""
    log_err "Installation failed or cancelled. Cleaning up..."

    if [ "$DIR_WAS_CREATED_BY_SCRIPT" -eq 1 ] && [ -n "${INSTALL_DIR:-}" ]; then
        rm -rf "${INSTALL_DIR}"
    elif [ -d "${INSTALL_DIR:-}" ]; then
        rm -f "${INSTALL_DIR}/compose.yaml" \
            "${INSTALL_DIR}/nginx.conf" \
            "${INSTALL_DIR}/settings.yaml" \
            "${INSTALL_DIR}/casdoor_init.json" \
            "${INSTALL_DIR}/.secrets"
        rm -rf "${INSTALL_DIR}/certs"
    fi

    if [ -n "${TEMP_DIR}" ] && [ -d "${TEMP_DIR}" ]; then
        rm -rf "${TEMP_DIR}"
    fi

    trap - EXIT
    exit 1
}

exit_cleanup() {
    local exit_code=$?
    [ "${exit_code}" -eq 0 ] && return
    cleanup
}

trap 'cleanup' INT TERM
trap 'exit_cleanup' EXIT

################################################################################
# GUM BOOTSTRAP LOGIC
################################################################################

verify_checksum() {
    local file="$1"
    local expected="$2"
    local actual

    actual=$(sha256sum "$file" | cut -d ' ' -f1)

    if [ "$actual" != "$expected" ]; then
        echo "Checksum failed for $file"
        echo "Expected: $expected"
        echo "Actual:   $actual"
        return 1
    fi
}

ensure_gum() {
    [ "${NO_GUM}" -eq 1 ] && return 1
    command -v gum > /dev/null 2>&1 && return 0

    echo "Gum not found locally. Attempting to bootstrap gum v0.17.0..." >&2

    local GUM_VERSION="0.17.0"
    local CHECKSUMS_FILE_HASH="daf9b5a189631771edf2364ad239862aa120b43a62ed7b5e501d1478b031db78"
    local BASE_URL="https://github.com/charmbracelet/gum/releases/download/v${GUM_VERSION}"
    local OS ARCH TARGET_PLATFORM

    if [ -n "${GUM_ARCH_OVERRIDE:-}" ]; then
        TARGET_PLATFORM="${GUM_ARCH_OVERRIDE}"
    else
        OS=$(uname -s)
        ARCH=$(uname -m)

        case "$OS" in
            Linux)   OS="Linux" ;;
            Darwin)  OS="Darwin" ;;
            *)
                echo "Warning: Unsupported OS for Gum auto-download: $OS." >&2
                return 1
                ;;
        esac

        case "$ARCH" in
            x86_64 | amd64) ARCH="x86_64" ;;
            aarch64 | arm64) ARCH="arm64" ;;
            i386 | i686)    ARCH="i386" ;;
            armv7*)         ARCH="armv7" ;;
            armv6*)         ARCH="armv6" ;;
            *)
                echo "Warning: Unsupported architecture for Gum auto-download: $ARCH" >&2
                return 1
                ;;
        esac

        TARGET_PLATFORM="${OS}_${ARCH}"
    fi

    local TAR_FILENAME="gum_${GUM_VERSION}_${TARGET_PLATFORM}.tar.gz"

    TEMP_DIR=$(mktemp -d)

    echo "Downloading checksums..." >&2
    if ! curl -fsSL -o "${TEMP_DIR}/checksums.txt" "${BASE_URL}/checksums.txt"; then
        echo "Warning: Failed to download checksums.txt" >&2
        return 1
    fi

    if ! verify_checksum "${TEMP_DIR}/checksums.txt" "$CHECKSUMS_FILE_HASH"; then
        return 1
    fi

    local escaped_tar_filename EXPECTED_BIN_HASH
    # shellcheck disable=SC2016
    escaped_tar_filename=$(printf '%s' "${TAR_FILENAME}" | sed 's/[.[\*^$(){}+?|\\/]/\\&/g')
    EXPECTED_BIN_HASH=$(sed -n "s/^[[:space:]]*\\([^[:space:]]\\+\\)[[:space:]]\\+${escaped_tar_filename}\$/\\1/p" "${TEMP_DIR}/checksums.txt" | head -n 1)

    if [ -z "$EXPECTED_BIN_HASH" ]; then
        echo "Warning: Could not find checksum for ${TAR_FILENAME}."
        return 1
    fi

    echo "Downloading ${TAR_FILENAME}..." >&2
    if ! curl -fsSL -o "${TEMP_DIR}/${TAR_FILENAME}" "${BASE_URL}/${TAR_FILENAME}"; then
        echo "Warning: Failed to download ${TAR_FILENAME}" >&2
        return 1
    fi

    if ! verify_checksum "${TEMP_DIR}/${TAR_FILENAME}" "$EXPECTED_BIN_HASH"; then
        return 1
    fi

    tar -xzf "${TEMP_DIR}/${TAR_FILENAME}" -C "${TEMP_DIR}"

    GUM_BIN_PATH=$(find "${TEMP_DIR}" -type f -name gum | head -n 1)
    if [ -z "$GUM_BIN_PATH" ]; then
        echo "Warning: Could not locate 'gum' binary after extraction." >&2
        return 1
    fi

    chmod +x "$GUM_BIN_PATH"

    gum() {
        "$GUM_BIN_PATH" "$@"
    }

    export GUM_BIN_PATH
    return 0
}

spin_or_die() {
    local spinner="$1"
    local title="$2"
    shift 2
    local cmd="$*"

    if [ "${NO_GUM}" -eq 0 ]; then
        local logfile
        logfile=$(mktemp)

        if ! gum spin --spinner "${spinner}" --title "${title}" --show-error -- bash -c "${cmd} > '${logfile}' 2>&1"; then
            echo ""
            gum style --foreground "${COLOR_WARN}" --bold "Command Failed!"
            gum style --foreground "${COLOR_WARN}" "Step: ${title}"
            gum style --foreground "${COLOR_WARN}" "Command: ${cmd}"
            _extra_args=()
            _term_cols=$(tput cols)
            if [ "$(wc -m < "${logfile}")" -ge $((_term_cols - 4)) ]; then
                _extra_args=(--width $((_term_cols - 2)))
            fi
            gum style "${_extra_args[@]}" --border normal --padding "0 1" --border-foreground "${COLOR_WARN}" "$(cat "${logfile}")"
            rm -f "${logfile}"
            exit 1
        fi
        rm -f "${logfile}"
    else
        echo ">> ${title}"
        if ! bash -c "${cmd}"; then
             log_err "Command Failed: ${cmd}"
             exit 1
        fi
    fi
}

################################################################################
# COMPRESSED DATA CHUNKS
################################################################################
CASDOOR_INIT_JSON_DATA='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'

NGINX_CONFIG='H4sICDtG2mgCA25naW54LmNvbmYA7VOxbtswEN39FTcIyORKQQ3UdsYCRboFAQJ0IxjyZBOheMwd
ldgt8u+lItlqHdvIlg7lRN57j0c+PjY6QrFOKao2rlhbhMJQCGiSo7Cv/ZpAHhZr3foEQ/XqtXhx
AcaT5NXLZCLIT8gD3TtJGGBezaue2qMq6AbBk9F+TZL+ghI9YBCguu7LjKnlAJ+rS+jOKMuyLDpR
wfjYoiTVsjvdeDabgYh/21ydbNrXxSuDnFztjE4IJSZThpULm1IwTjvoU8Tm6hhZPeD2UJBLPf9V
YLzDkFSjN+qe7FaJ+4lwuUM7XzrroRwu043ItNmqqEX2NugYl4uqGpwdSYJJrTG/DsN1Nmp429Ho
o8wf01vUfvr9BrKxDeVbaGv5rOAb8bNmi7abQdEzskptVL2Dutk7N7lhSgSFmDU2eEZztwvpn5E9
w/+6z/KxXB8KGa3jTBkDOGL3bV0ju7AawZdTyVvk8Q8mD5mJc4xWCLPFl7e/alkM54rEB1/s3dnM
exktloiX8//x/PB4/gbqdx6+3wUAAA=='

SEP_COMPOSE_YAML='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'

SEP_SETTINGS_YAML='H4sICHh8MmkAA3NldHRpbmdzLnlhbWwAzZdLb9s4EMfv/RREUcBAsbGdNts2OpWWGJuwHl5SSpO9
ELLM2t7YklZSEhiBv/sO9bAettPd7qXJIRD/Q/I3w+FwEifR4jHI1lEoFlHwIBPtDULYNJ1vQnds
3WOM2K7ghHPq2FxDWfIoKwtiiInDXa6mIHSB3r5/qyTPnQiPEyYsxyCmhvw47m+jhdykfd1PF1GU
eKlMwHKE9SmxDdiIceEwOqb2Ya1VlsWpNhhcfvjcH8Lvpfbl6uoKRB1zw3FYYVdhUM49wgCv975X
CLOZSXXsArSwsUU0lMr4AkhyVSfMpTdKJ2KG3YmGBiAN/nrO+rHcFiYmVY5TQ0PvXso9IQwzcRD2
TTtOdEbcM7aFWNiDvzOH2mCqPAQHgyIk2pfhcJhb3DAH5tR2g4F2DT+55rAxtumfHb9UVIhJ2H0R
lBHBrjBGHqMaiqM0WyYy/XsDW1Uf2rsXRVeF3xhBEDj/5jBj/3Ux136/+vihXojrE2Lhah8YZM4U
ztZjcLKJXKzVIRV/P338fD0ofIC1lBF3VYSNkYYCuZHJTjxHCaSYSDM/U1lkYBePMCdaGRpIANJk
zodVimloMc8/mj4jVGGruJ/zqDB0GKxxcExlZ70PDFH7Fg7KqSLY5jpL1mHr0v0HviPCE4wIcW4K
lbo31CRlygYyqXNW6VNy35Af5K5UYftf2rfDCYj2DVHptQ6fZJhFkD9+vNauh8PL4jKoSlO5wYhB
GdFdkaf9IPIfsxXcrc1m7gcPRXRsOpuRqlrBPaOmCzlK7lxiF8WtFFT56aer8ovf27oAHMJuMaT8
pyHEIIjCRYE9M726aqmJLz0VqB5UIlpR935DPSiFnklEpa2bGhDnVUgJg5aicw41BKLZnrN/U4S8
3Ly8okKfYHsM141yPDLJ/piIByu59ZG+8sOlPEHlbzKZpEdI9XCLpxzuwmCmT+jtaxg4CVbrp5MA
hXICoSG0Icq1uhQqG70Zf4ViBHnxGKcnKOa5csQwrye0EKrxLoLl2GMHbsOPUawoXEbGCP0ISWyV
4RmwWjxBV4pdRMgbfco96zU4fSWDh/RxeworaGotppbSAqqVozQuL+hrGRyu41hmyPJDfymTE0hp
YXFM1BRaQAfhJ3j0aLORQYaMtb8MoZytA2T4mX8qtbPn46wuxtoJDWNdEBfzqbCwjcdQr87DuH76
8EpkMpCPw3IYbVEUo+XbyZy7ezEh2Mg7rLIB/H+vkXqPoLekbr1wWUGh6XTLnqnQZw40cvAq3Omm
ZxTtWqtSw8rrumoOoIlNu2ruTa2UzWy9ozOlpOymym7MjR5kWD0AioQ0HJ9ZlsibNHipqtevOVaE
Tb0bDb8uygFNTee7MMg74PJ9tKzao26LqB5AaJefZNJfbqK5v+mH0dZfaPW+6nndN+bjGVWBb6JB
tybyvtyF5s1uGt8SRm/uBRyWhr77m1Qe8Vo7/ofZIaZj22GkfHh4E/4Cpbu09R3L5HuUbH1YQKT5
C9SSt7u65ShG1mFun/9P0pigbgE/0R3kp1t1BqrDyBMTN9PSL9MuX+KXboNsx8JGzdT19cSJYl13
PNvdf/0XSTLIR8/l9blk+PmL/g9r7U72XQ4AAA=='

################################################################################
# CONFIGURATION & DEFAULTS
################################################################################
CONTAINER_ENGINE="${CONTAINER_ENGINE:-docker}"
CREATE_PMM_CONTAINER="${CREATE_PMM_CONTAINER:-1}"
INSTALL_DIR="${INSTALL_DIR:-"${HOME}/sep"}"
SEP_IMAGE_NAME="${SEP_IMAGE_NAME:-docker.io/percona/percona-sep}"
SEP_IMAGE_TAG="${SEP_IMAGE_TAG:-v0.9}"
SEP_HTTP_PORT="${SEP_HTTP_PORT:-8080}"
SEP_HTTPS_PORT="${SEP_HTTPS_PORT:-8444}"
SEP_PMM_PUBLIC_HOST="${SEP_PMM_PUBLIC_HOST:-127.0.0.1}"
SEP_PMM_PORT="${SEP_PMM_PORT:-8443}"
SEP_PMM_FRONTEND="${SEP_PMM_FRONTEND:-https://${SEP_PMM_PUBLIC_HOST}}"
SEP_PMM_NOMAD_DATA_DIR="${SEP_PMM_NOMAD_DATA_DIR:-${INSTALL_DIR}/nomad_data}"
SEP_PMM_CONTAINER_NAME="${SEP_PMM_CONTAINER_NAME:-sep-pmm-1}"
SEP_PMM_URL_AUTH_ACCOUNT_USER="${SEP_PMM_URL_AUTH_ACCOUNT_USER:-}"
SEP_PMM_URL_AUTH_ACCOUNT_PASS="${SEP_PMM_URL_AUTH_ACCOUNT_PASS:-}"
if [[ (-z ${SEP_PMM_URL_AUTH_ACCOUNT_USER} || -z ${SEP_PMM_URL_AUTH_ACCOUNT_PASS}) && -n ${SEP_PMM_URL_AUTH_ACCOUNT:-}       ]]; then
    SEP_PMM_URL_AUTH_ACCOUNT_USER="${SEP_PMM_URL_AUTH_ACCOUNT%%:*}"
    SEP_PMM_URL_AUTH_ACCOUNT_PASS="${SEP_PMM_URL_AUTH_ACCOUNT#*:}"
fi
DOCKER_TOKEN="${DOCKER_TOKEN:-}"
CERTLIST="${CERTLIST:-all-in-one}"

# Plugin Mappings
PLUGIN_DISP_SCHEMA="Schema Change"
PLUGIN_DISP_ARCHIVE="Archive"
PLUGIN_DISP_BACKUPS="MySQL Backups"
PLUGIN_DISP_CHECKSUMS="Checksums"
PLUGIN_DISP_SNIPPETS="Collect Diagnostic Data (Snippets)"
PLUGIN_DISP_TASK="Task Manager"
PLUGIN_DISP_MONGO="MongoDB Backups"

# Default enabled (Internal Names)
SEP_ENABLED_PLUGINS="${SEP_ENABLED_PLUGINS:-schema_change,archive,backups,checksums,snippets}"

# Logic Flags
AUTOSTART="${AUTOSTART:-0}"
if [ -z "${NO_INTERACTION:-}" ]; then
    is_tty && NO_INTERACTION=0 || NO_INTERACTION=1
fi
# Track which args provided by CLI to skip prompts
SET_CLI_INSTALL_DIR=0
SET_CLI_PLUGINS=0
SET_CLI_PMM=0

################################################################################
# CLI ARGUMENT PARSING
################################################################################

usage() {
    cat << EOF
SEP Installer

USAGE
  ./sep_installer.sh [OPTIONS]

OPTIONS
  --install-dir DIR        Set installation directory (Default: ~/sep)
  --http-port PORT         Set HTTP port (Default: 8080)
  --https-port PORT        Set HTTPS port (Default: 8444)
  --plugins LIST           Comma-separated list of plugins (internal names)
                           Available: schema_change, archive, backups, checksums, snippets, task_manager, mongodb_backups
                           Default: schema_change,archive,backups,checksums,snippets
  --create-pmm-container   Create PMM container as part of the stack (Default)
  --use-existent-pmm       Use an external/existing PMM instance (removes PMM from stack)
  --pmm-user USER          PMM Username (for PMM 3 Nomad auth)
  --pmm-pass PASS          PMM Password (for PMM 3 Nomad auth)
  --pmm-token TOKEN        PMM Service Account Token (for PMM Inventory Sync)
  --engine ENGINE          Container engine: docker or podman (Default: docker if available, else podman)
  --docker-token TOKEN     Token for registry login if needed
  --autostart              Start the stack automatically after install
  --no-interaction         Skip interactive wizard and use defaults/flags
  --help, -h               Show this help message

EXAMPLES
  ./sep_installer.sh --http-port 9090
  ./sep_installer.sh --no-interaction --use-existent-pmm --autostart
EOF
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --install-dir)
                INSTALL_DIR="$2"
                SET_CLI_INSTALL_DIR=1
                shift 2
                ;;
            --http-port)
                SEP_HTTP_PORT="$2"
                shift 2
                ;;
            --https-port)
                SEP_HTTPS_PORT="$2"
                shift 2
                ;;
            --plugins)
                SEP_ENABLED_PLUGINS="$2"
                SET_CLI_PLUGINS=1
                shift 2
                ;;
            --engine)
                CONTAINER_ENGINE="$2"
                shift 2
                ;;
            --docker-token)
                DOCKER_TOKEN="$2"
                shift 2
                ;;
            --create-pmm-container)
                CREATE_PMM_CONTAINER=1
                SET_CLI_PMM=1
                shift
                ;;
            --use-existent-pmm)
                CREATE_PMM_CONTAINER=0
                SET_CLI_PMM=1
                shift
                ;;
            --pmm-user)
                SEP_PMM_URL_AUTH_ACCOUNT_USER="$2"
                shift 2
                ;;
            --pmm-pass)
                SEP_PMM_URL_AUTH_ACCOUNT_PASS="$2"
                shift 2
                ;;
            --pmm-token)
                SEP_PMM_URL_AUTH_TOKEN="$2"
                shift 2
                ;;
            --autostart)
                AUTOSTART=1
                shift
                ;;
            --no-interaction | --headless | --yes | -y)
                NO_INTERACTION=1
                shift
                ;;
            --help | -h)
                usage
                exit 0
                ;;
            *)
                if [ "${1#-}" != "$1" ]; then
                    echo "Unknown option: $1"
                    exit 1
                fi
                shift
                ;;
        esac
    done
}

################################################################################
# PLUGIN LOGIC
################################################################################

get_display_name() {
    case "$1" in
        schema_change) echo "$PLUGIN_DISP_SCHEMA" ;;
        archive) echo "$PLUGIN_DISP_ARCHIVE" ;;
        backups) echo "$PLUGIN_DISP_BACKUPS" ;;
        checksums) echo "$PLUGIN_DISP_CHECKSUMS" ;;
        snippets) echo "$PLUGIN_DISP_SNIPPETS" ;;
        task_manager) echo "$PLUGIN_DISP_TASK" ;;
        mongodb_backups) echo "$PLUGIN_DISP_MONGO" ;;
        *) echo "$1" ;;
    esac
}

get_internal_name() {
    case "$1" in
        "$PLUGIN_DISP_SCHEMA") echo "schema_change" ;;
        "$PLUGIN_DISP_ARCHIVE") echo "archive" ;;
        "$PLUGIN_DISP_BACKUPS") echo "backups" ;;
        "$PLUGIN_DISP_CHECKSUMS") echo "checksums" ;;
        "$PLUGIN_DISP_SNIPPETS") echo "snippets" ;;
        "$PLUGIN_DISP_TASK") echo "task_manager" ;;
        "$PLUGIN_DISP_MONGO") echo "mongodb_backups" ;;
        *) echo "$1" ;;
    esac
}

init_plugin_disable_markers() {
    local plugins_to_check=(
        "schema_change"
        "archive"
        "backups"
        "checksums"
        "snippets"
        "task_manager"
        "mongodb_backups"
    )
    local var_name disable_char

    for plugin in "${plugins_to_check[@]}"; do
        var_name="SEP_PLUGINS_${plugin^^}_DISABLE"
        [[ ",${SEP_ENABLED_PLUGINS}," == *",${plugin},"* ]] && disable_char="" || disable_char="#"
        printf -v "${var_name}" "%s" "${disable_char}"
        export "${var_name?}"
    done
}

################################################################################
# CORE FUNCTIONS
################################################################################

check_prereqs() {
    banner
    if [ "${NO_GUM}" -eq 0 ]; then
        gum style --foreground "$COLOR_SEC" "Checking System Requirements..."
    else
        echo "Checking System Requirements..."
    fi

    CHECK_LIST="openssl sed find gunzip"

    if command -v docker > /dev/null 2>&1; then
        CONTAINER_ENGINE="docker"
    elif command -v podman > /dev/null 2>&1; then
        CONTAINER_ENGINE="podman"
    else
        log_err "Neither Docker nor Podman found."
        exit 1
    fi

    for tool in $CHECK_LIST; do
        if [ "${NO_GUM}" -eq 0 ]; then
             gum spin --spinner dot --title "Checking for $tool..." -- sleep 0.1
        else
             printf "Checking for %s... " "$tool"
             sleep 0.1
        fi

        if ! command -v "$tool" > /dev/null 2>&1; then
            if [ "${NO_GUM}" -eq 1 ]; then echo "MISSING"; fi
            log_err "Missing required software: $tool"
            exit 1
        else
            if [ "${NO_GUM}" -eq 1 ]; then echo "OK"; fi
        fi
    done

    log_info "All prerequisites met. Using engine: ${CONTAINER_ENGINE}"
}

get_user_input() {
    if [ "${NO_GUM}" -eq 0 ]; then
        get_user_input_gum
    else
        get_user_input_text
    fi
}

get_user_input_gum() {
    gum style --foreground "$COLOR_SEC" "Configuration Wizard"

    if [ "$SET_CLI_INSTALL_DIR" -eq 0 ]; then
        INSTALL_DIR=$(gum input --placeholder "Install Directory" --value "$INSTALL_DIR" --header "Where should files be generated?")
    fi

    if [ "$SET_CLI_PLUGINS" -eq 0 ]; then
        echo "Select enabled plugins (Space to select, Enter to confirm):"
        ALL_PLUGINS_DISP="${PLUGIN_DISP_SCHEMA},${PLUGIN_DISP_ARCHIVE},${PLUGIN_DISP_BACKUPS},${PLUGIN_DISP_CHECKSUMS},${PLUGIN_DISP_SNIPPETS},${PLUGIN_DISP_TASK},${PLUGIN_DISP_MONGO}"
        DEFAULT_SELECTION=""
        OLD_IFS="$IFS"
        IFS=","
        for p in $SEP_ENABLED_PLUGINS; do
            dname=$(get_display_name "$p")
            if [ -z "$DEFAULT_SELECTION" ]; then DEFAULT_SELECTION="$dname"; else DEFAULT_SELECTION="$DEFAULT_SELECTION,$dname"; fi
        done
        IFS="$OLD_IFS"

        SELECTED_DISP=$(echo "$ALL_PLUGINS_DISP" | tr ',' '\n' | gum choose --no-limit --selected "$DEFAULT_SELECTION" --height 10 --header "Enable Plugins")

        NEW_PLUGIN_LIST=""
        if [ -n "$SELECTED_DISP" ]; then
            OLD_IFS="$IFS"
            IFS='
'
            for line in $SELECTED_DISP; do
                iname=$(get_internal_name "$line")
                if [ -z "$NEW_PLUGIN_LIST" ]; then NEW_PLUGIN_LIST="$iname"; else NEW_PLUGIN_LIST="$NEW_PLUGIN_LIST,$iname"; fi
            done
            IFS="$OLD_IFS"
        fi
        SEP_ENABLED_PLUGINS="$NEW_PLUGIN_LIST"
    fi

    if [ "$SET_CLI_PMM" -eq 0 ]; then
        if gum confirm "Create PMM Container?"; then
            CREATE_PMM_CONTAINER=1
        else
            CREATE_PMM_CONTAINER=0
        fi
    fi
    if [ "$CREATE_PMM_CONTAINER" -eq 0 ]; then
        gum style --foreground "$COLOR_SUBTLE" "External PMM Configuration"

        if [ -z "${SEP_PMM_URL_AUTH_ACCOUNT_USER}" ]; then
            SEP_PMM_URL_AUTH_ACCOUNT_USER=$(gum input --placeholder "admin" --value "admin" --header "PMM User")
        fi

        if [ -z "${SEP_PMM_URL_AUTH_ACCOUNT_PASS}" ]; then
            SEP_PMM_URL_AUTH_ACCOUNT_PASS=$(gum input --password --prompt "${SEP_PMM_URL_AUTH_ACCOUNT_USER}:" --header "PMM Password")
        fi

        if [ -z "${SEP_PMM_URL_AUTH_TOKEN:-}" ]; then
            SEP_PMM_URL_AUTH_TOKEN=$(gum input --password --placeholder "Auth Token" --header "Enter PMM Service Account Token")
        fi

        SEP_PMM_URL_AUTH_ACCOUNT="${SEP_PMM_URL_AUTH_ACCOUNT_USER}:${SEP_PMM_URL_AUTH_ACCOUNT_PASS}"
        export SEP_PMM_URL_AUTH_ACCOUNT SEP_PMM_URL_AUTH_TOKEN
    fi
}

get_user_input_text() {
    echo "--- Configuration Wizard ---"

    if [ "$SET_CLI_INSTALL_DIR" -eq 0 ]; then
        read -r -p "Install Directory [${INSTALL_DIR}]: " _input
        if [ -n "$_input" ]; then INSTALL_DIR="$_input"; fi
    fi

    if [ "$SET_CLI_PLUGINS" -eq 0 ]; then
        echo ""
        echo "Available Plugins: schema_change, archive, backups, checksums, snippets, task_manager, mongodb_backups"
        echo "Current Selection: ${SEP_ENABLED_PLUGINS}"
        read -r -p "Enter plugins list (comma separated) or press Enter to keep current: " _input
        if [ -n "$_input" ]; then SEP_ENABLED_PLUGINS="$_input"; fi
    fi

    if [ "$SET_CLI_PMM" -eq 0 ]; then
        read -r -p "Create PMM Container? [Y/n] " _yn
        case "$_yn" in
            [Nn]*) CREATE_PMM_CONTAINER=0 ;;
            *) CREATE_PMM_CONTAINER=1 ;;
        esac
    fi

    if [ "$CREATE_PMM_CONTAINER" -eq 0 ]; then
        echo "--- External PMM Configuration ---"
        if [ -z "${SEP_PMM_URL_AUTH_ACCOUNT_USER}" ]; then
            read -rp "PMM User [admin]: " _input
            SEP_PMM_URL_AUTH_ACCOUNT_USER="${_input:-admin}"
        fi

        if [ -z "${SEP_PMM_URL_AUTH_ACCOUNT_PASS}" ]; then
            read -rsp "PMM Password: " SEP_PMM_URL_AUTH_ACCOUNT_PASS
            echo ""
        fi

        if [ -z "${SEP_PMM_URL_AUTH_TOKEN:-}" ]; then
            read -rsp "PMM Service Account Token: " SEP_PMM_URL_AUTH_TOKEN
            echo ""
        fi
        SEP_PMM_URL_AUTH_ACCOUNT="${SEP_PMM_URL_AUTH_ACCOUNT_USER}:${SEP_PMM_URL_AUTH_ACCOUNT_PASS}"
        export SEP_PMM_URL_AUTH_ACCOUNT SEP_PMM_URL_AUTH_TOKEN
    fi
}

summary_screen() {
    if [ "${NO_GUM}" -eq 0 ]; then
        summary_screen_gum
    else
        summary_screen_text
    fi
}

summary_screen_gum() {
    while true; do
        clear_screen
        banner
        gum style --bold --foreground "$COLOR_PRIMARY" "Configuration Summary"

        DISPLAY_PLUGINS=""
        OLD_IFS="$IFS"
        IFS=","
        for p in $SEP_ENABLED_PLUGINS; do
            if [ -z "$DISPLAY_PLUGINS" ]; then DISPLAY_PLUGINS="$p"; else DISPLAY_PLUGINS="$DISPLAY_PLUGINS, $p"; fi
        done
        IFS="$OLD_IFS"

        if [ "$CREATE_PMM_CONTAINER" -eq 1 ]; then DISP_PMM="Yes"; else DISP_PMM="No"; fi

        CHOICE=$(echo "|Install Dir|${INSTALL_DIR}
|Create PMM|${DISP_PMM}
|Plugins|${DISPLAY_PLUGINS}
|HTTP Port|${SEP_HTTP_PORT}
|HTTPS Port|${SEP_HTTPS_PORT}
Submit||" | gum table --border normal --columns ",Setting,Value" --widths 7,20,60 --separator="|" --no-show-help)

        KEY=$(echo "$CHOICE" | cut -d"|" -f2)
        ACTION=$(echo "$CHOICE" | cut -d"|" -f1)

        if [ "$ACTION" = "Submit" ]; then
            gum confirm "Proceed with installation?" && break || exit 1
        elif [ "$KEY" = "Install Dir" ]; then
            INSTALL_DIR=$(gum input --value "$INSTALL_DIR" --header "Enter new Install Directory")
        elif [ "$KEY" = "Create PMM" ]; then
            if [ "$CREATE_PMM_CONTAINER" -eq 1 ]; then
                CREATE_PMM_CONTAINER=0
                gum style --foreground "$COLOR_SUBTLE" "Switching to External PMM: Credentials Required"
                SEP_PMM_URL_AUTH_ACCOUNT_USER=$(gum input --placeholder "admin" --value "${SEP_PMM_URL_AUTH_ACCOUNT_USER:-admin}" --header "PMM User")
                _curr_pass="${SEP_PMM_URL_AUTH_ACCOUNT_PASS}"
                [ -z "$_curr_pass" ] && [ "${SEP_PMM_URL_AUTH_ACCOUNT_USER}" == "admin" ] && _curr_pass="admin"
                SEP_PMM_URL_AUTH_ACCOUNT_PASS=$(gum input --password --value "$_curr_pass" --header "PMM Password")
                SEP_PMM_URL_AUTH_TOKEN=$(gum input --password --value "${SEP_PMM_URL_AUTH_TOKEN:-}" --placeholder "Auth Token" --header "Enter PMM Service Account Token")
                SEP_PMM_URL_AUTH_ACCOUNT="${SEP_PMM_URL_AUTH_ACCOUNT_USER}:${SEP_PMM_URL_AUTH_ACCOUNT_PASS}"
                export SEP_PMM_URL_AUTH_ACCOUNT SEP_PMM_URL_AUTH_TOKEN
            else
                CREATE_PMM_CONTAINER=1
            fi
        elif [ "$KEY" = "HTTP Port" ]; then
            SEP_HTTP_PORT=$(gum input --value "$SEP_HTTP_PORT" --placeholder "8080" --header "Enter new HTTP Port")
        elif [ "$KEY" = "HTTPS Port" ]; then
            SEP_HTTPS_PORT=$(gum input --value "$SEP_HTTPS_PORT" --placeholder "8444" --header "Enter new HTTPS Port")
        elif [ "$KEY" = "Plugins" ]; then
            ALL_PLUGINS_DISP="${PLUGIN_DISP_SCHEMA},${PLUGIN_DISP_ARCHIVE},${PLUGIN_DISP_BACKUPS},${PLUGIN_DISP_CHECKSUMS},${PLUGIN_DISP_SNIPPETS},${PLUGIN_DISP_TASK},${PLUGIN_DISP_MONGO}"
            DEFAULT_SELECTION=""
            OLD_IFS="$IFS"
            IFS=","
            for p in $SEP_ENABLED_PLUGINS; do
                dname=$(get_display_name "$p")
                if [ -z "$DEFAULT_SELECTION" ]; then DEFAULT_SELECTION="$dname"; else DEFAULT_SELECTION="$DEFAULT_SELECTION,$dname"; fi
            done
            IFS="$OLD_IFS"
            SELECTED_DISP=$(echo "$ALL_PLUGINS_DISP" | tr ',' '\n' | gum choose --no-limit --selected "$DEFAULT_SELECTION" --height 10 --header "Enable Plugins")
            NEW_PLUGIN_LIST=""
            if [ -n "$SELECTED_DISP" ]; then
                OLD_IFS="$IFS"
                IFS='
'
                for line in $SELECTED_DISP; do
                    iname=$(get_internal_name "$line")
                    if [ -z "$NEW_PLUGIN_LIST" ]; then NEW_PLUGIN_LIST="$iname"; else NEW_PLUGIN_LIST="$NEW_PLUGIN_LIST,$iname"; fi
                done
                IFS="$OLD_IFS"
            fi
            SEP_ENABLED_PLUGINS="$NEW_PLUGIN_LIST"
        else
            gum confirm "Do you want to cancel the installation?" && exit 1
        fi
    done
}

summary_screen_text() {
    clear_screen
    banner
    echo "--- Configuration Summary ---"
    echo "Install Dir: ${INSTALL_DIR}"
    if [ "$CREATE_PMM_CONTAINER" -eq 1 ]; then echo "Create PMM:  Yes"; else echo "Create PMM:  No"; fi
    echo "Plugins:     ${SEP_ENABLED_PLUGINS}"
    echo "HTTP Port:   ${SEP_HTTP_PORT}"
    echo "HTTPS Port:  ${SEP_HTTPS_PORT}"
    echo "-----------------------------"

    read -r -p "Proceed with installation? [Y/n] " _yn
    case "$_yn" in
        [Nn]*)
            log_err "Installation cancelled by user."
            exit 1
            ;;
        *) return 0 ;;
    esac
}

generate_tls() {
    test "${DEBUG:-0}" = 0 || set -o xtrace
    ABS_INSTALL_DIR="$1"
    CERTLIST="$2"

    mkdir -p "${ABS_INSTALL_DIR}/certs"
    cd "${ABS_INSTALL_DIR}/certs"

    chmod -R u+w . 2> /dev/null || true

    openssl genpkey -algorithm RSA -out sep_token_jwt_key.key -pkeyopt rsa_keygen_bits:4096 2> /dev/null
    openssl rsa -pubout -in sep_token_jwt_key.key -out sep_token_jwt_key.pem 2> /dev/null

    openssl ecparam -genkey -name secp384r1 -out sep-ca-key.pem -noout
    openssl req -new -x509 -key sep-ca-key.pem -nodes -out sep-ca.pem \
        -sha384 -days 365 -subj "/CN=SEP Root CA" \
        -addext "keyUsage=critical,digitalSignature,keyCertSign" \
        -addext "basicConstraints=critical,CA:true,pathlen:0" \
        -addext "subjectKeyIdentifier=hash" \
        -addext "authorityKeyIdentifier=keyid:always" \
        -addext "extendedKeyUsage=serverAuth,clientAuth" 2> /dev/null

    cat <<- EOS > openssl.base.conf
    [ req ]
    distinguished_name = req_distinguished_name
    req_extensions = v3_req

    [ req_distinguished_name ]

    [ v3_req ]
    authorityKeyIdentifier = keyid:always,issuer
    basicConstraints = critical,CA:FALSE
    keyUsage = critical, digitalSignature, keyEncipherment
    extendedKeyUsage = serverAuth, clientAuth
    subjectAltName = @alt_names

    [alt_names]
EOS

    for cert in $(echo "${CERTLIST}" | tr , " "); do
        cp openssl.base.conf openssl.conf

        printf 'DNS.1=localhost\nDNS.2=%s\nDNS.3=%s\nDNS.4=inventory_api\nDNS.5=tasks_api\nDNS.6=app' sep '*.sep' >> openssl.conf
        printf "\nIP.1=%s\n" 127.0.0.1 >> openssl.conf

        openssl ecparam -genkey -name secp384r1 -out "${cert}-cert-key.pem" -noout
        openssl req -new -key "${cert}-cert-key.pem" -out "${cert}-cert.csr" -subj "/CN=${cert}" 2> /dev/null
        openssl x509 -req -in "${cert}-cert.csr" -CA sep-ca.pem -CAkey sep-ca-key.pem -CAcreateserial -out "${cert}-cert.pem" -days 365 -sha384 -extfile ./openssl.conf -extensions v3_req 2> /dev/null

        rm -f "${cert}-cert.csr" openssl.conf
    done

    rm -f openssl.base.conf
    find . -type f -exec chmod 0444 {} \;
}

perform_template_rendering() {
    test "${DEBUG:-0}" = 0 || set -o xtrace
    ABS_INSTALL_DIR="$1"

    local pmm_marker="#---PMM---#"
    local remove_pmm_block_expr="/^${pmm_marker//\//\\/}\$/d"
    if [ "$CREATE_PMM_CONTAINER" -eq 0 ]; then
        remove_pmm_block_expr="/^${pmm_marker//\//\\/}\$/,/^${pmm_marker//\//\\/}\$/d"
    fi

    for file_var in "CASDOOR_INIT_JSON_DATA:${ABS_INSTALL_DIR}/casdoor_init.json" \
        "NGINX_CONFIG:${ABS_INSTALL_DIR}/nginx.conf" \
        "SEP_COMPOSE_YAML:${ABS_INSTALL_DIR}/compose.yaml" \
        "SEP_SETTINGS_YAML:${ABS_INSTALL_DIR}/settings.yaml"; do

        data_var_name="${file_var%%:*}"
        outfile="${file_var#*:}"

        printf '%s' "${!data_var_name}" | base64 -d | gunzip > "${outfile}.tmp"

        sed \
            -e "s|\${SEP_HTTP_PORT}|${SEP_HTTP_PORT}|g" \
            -e "s|\${SEP_HTTPS_PORT}|${SEP_HTTPS_PORT}|g" \
            -e "s|\${INSTALL_DIR}|${ABS_INSTALL_DIR}|g" \
            -e "s|\${SEP_PMM_PUBLIC_HOST}|${SEP_PMM_PUBLIC_HOST}|g" \
            -e "s|\${SEP_PMM_PUBLIC_ADDRESS}|${SEP_PMM_PUBLIC_HOST}|g" \
            -e "s|\${SEP_PMM_PORT}|${SEP_PMM_PORT}|g" \
            -e "s|\${SEP_PMM_FRONTEND}|${SEP_PMM_FRONTEND}|g" \
            -e "s|\${SEP_PMM_URL_AUTH_TOKEN}|${SEP_PMM_URL_AUTH_TOKEN}|g" \
            -e "s|\${SEP_PMM_URL_AUTH_ACCOUNT}|${SEP_PMM_URL_AUTH_ACCOUNT}|g" \
            -e "s|\${SEP_IMAGE_NAME}|${SEP_IMAGE_NAME}|g" \
            -e "s|\${SEP_IMAGE_TAG}|${SEP_IMAGE_TAG}|g" \
            -e "s|\${CASDOOR_SEP_CLIENT_ID}|${CASDOOR_SEP_CLIENT_ID}|g" \
            -e "s|\${CASDOOR_SEP_CLIENT_SECRET}|${CASDOOR_SEP_CLIENT_SECRET}|g" \
            -e "s|\${SEP_BACKEND_DB_PASSWORD}|${SEP_BACKEND_DB_PASSWORD}|g" \
            -e "s|\${CASDOOR_DEFAULT_ORG_SALT}|${CASDOOR_DEFAULT_ORG_SALT}|g" \
            -e "s|\${CASDOOR_SEP_ORG_SALT}|${CASDOOR_SEP_ORG_SALT}|g" \
            -e "s|\${CASDOOR_DEFAULT_CLIENT_SECRET}|${CASDOOR_DEFAULT_CLIENT_SECRET}|g" \
            -e "s|\${CASDOOR_DEFAULT_CLIENT_ID}|${CASDOOR_DEFAULT_CLIENT_ID}|g" \
            -e "s|\${CASDOOR_DEFAULT_ADMIN_PASSWD}|${CASDOOR_DEFAULT_ADMIN_PASSWD}|g" \
            -e "s|\${CASDOOR_SEP_ADMIN_PASSWD}|${CASDOOR_SEP_ADMIN_PASSWD}|g" \
            -e "s|\${CASDOOR_SEP_SEP_PASSWD}|${CASDOOR_SEP_SEP_PASSWD}|g" \
            -e "s|\${SEP_CASDOOR_CERTIFICATE_JSON}|${SEP_CASDOOR_CERTIFICATE_JSON}|g" \
            -e "s|\${SEP_CASDOOR_PRIVATE_KEY_JSON}|${SEP_CASDOOR_PRIVATE_KEY_JSON}|g" \
            -e "s|\${SEP_PLUGINS_SCHEMA_CHANGE_DISABLE}|${SEP_PLUGINS_SCHEMA_CHANGE_DISABLE}|g" \
            -e "s|\${SEP_PLUGINS_ARCHIVE_DISABLE}|${SEP_PLUGINS_ARCHIVE_DISABLE}|g" \
            -e "s|\${SEP_PLUGINS_BACKUPS_DISABLE}|${SEP_PLUGINS_BACKUPS_DISABLE}|g" \
            -e "s|\${SEP_PLUGINS_CHECKSUMS_DISABLE}|${SEP_PLUGINS_CHECKSUMS_DISABLE}|g" \
            -e "s|\${SEP_PLUGINS_SNIPPETS_DISABLE}|${SEP_PLUGINS_SNIPPETS_DISABLE}|g" \
            -e "s|\${SEP_PLUGINS_TASK_MANAGER_DISABLE}|${SEP_PLUGINS_TASK_MANAGER_DISABLE}|g" \
            -e "s|\${SEP_PLUGINS_MONGODB_BACKUPS_DISABLE}|${SEP_PLUGINS_MONGODB_BACKUPS_DISABLE}|g" \
            -e "${remove_pmm_block_expr}" \
            "${outfile}.tmp" > "${outfile}"

        rm -f "${outfile}.tmp"
    done
}

generate_secrets_and_render() {
    if [ -d "${INSTALL_DIR}" ] && [ "$(ls -A "${INSTALL_DIR}")" ]; then
        if [ "$NO_INTERACTION" -eq 0 ]; then
            if [ "${NO_GUM}" -eq 0 ]; then
                gum style --foreground "$COLOR_WARN" "Warning: Installation directory '${INSTALL_DIR}' already exists and is not empty."
                if ! gum confirm "Proceed anyway? (Existing files may be overwritten)"; then
                    log_err "Installation aborted by user."
                    exit 0
                fi
                gum spin --title "Preparing installation directory..." -- sleep 0.5
            else
                echo "Warning: Installation directory '${INSTALL_DIR}' already exists and is not empty."
                read -r -p "Proceed anyway? [Y/n] " _yn
                case "$_yn" in
                    [Nn]*) exit 0 ;;
                esac
            fi
        fi
    fi

    mkdir -p "${INSTALL_DIR}"
    ABS_INSTALL_DIR=$(cd "${INSTALL_DIR}" && pwd)

    set -a
    CASDOOR_DEFAULT_ORG_SALT=$(openssl rand -hex 8)
    CASDOOR_SEP_ORG_SALT=$(openssl rand -hex 8)
    CASDOOR_DEFAULT_CLIENT_ID=$(openssl rand -hex 10)
    CASDOOR_DEFAULT_CLIENT_SECRET=$(openssl rand -hex 20)
    CASDOOR_SEP_CLIENT_ID=$(openssl rand -hex 10)
    CASDOOR_SEP_CLIENT_SECRET=$(openssl rand -hex 20)
    CASDOOR_DEFAULT_ADMIN_PASSWD=$(openssl rand -hex 20)
    CASDOOR_SEP_ADMIN_PASSWD=$(openssl rand -hex 20)
    CASDOOR_SEP_SEP_PASSWD=$(openssl rand -hex 20)
    SEP_BACKEND_DB_PASSWORD=$(openssl rand -hex 20)
    SEP_PMM_URL_AUTH_ACCOUNT=${SEP_PMM_URL_AUTH_ACCOUNT:-admin:admin}
    SEP_PMM_URL_AUTH_TOKEN=${SEP_PMM_URL_AUTH_TOKEN:-CHANGEME}
    GF_SECURITY_ADMIN_PASSWORD=$(openssl rand -hex 20)
    set +a

    export -f generate_tls
    spin_or_die dot "Generating TLS Certificates..." "generate_tls '$ABS_INSTALL_DIR' '$CERTLIST'"

    SEP_CASDOOR_PRIVATE_KEY_JSON=$(sed -z 's/\n/\\\\n/g' "${ABS_INSTALL_DIR}/certs/sep_token_jwt_key.key")
    SEP_CASDOOR_CERTIFICATE_JSON=$(sed -z 's/\n/\\\\n/g' "${ABS_INSTALL_DIR}/certs/sep_token_jwt_key.pem")
    export SEP_CASDOOR_PRIVATE_KEY_JSON SEP_CASDOOR_CERTIFICATE_JSON

    touch "${INSTALL_DIR}/.secrets"
    chmod 640 "${INSTALL_DIR}/.secrets"

    cat << EOF > "${INSTALL_DIR}/.secrets"
CASDOOR_DEFAULT_ORG_SALT=${CASDOOR_DEFAULT_ORG_SALT}
CASDOOR_SEP_ORG_SALT=${CASDOOR_SEP_ORG_SALT}
CASDOOR_DEFAULT_CLIENT_ID=${CASDOOR_DEFAULT_CLIENT_ID}
CASDOOR_DEFAULT_CLIENT_SECRET=${CASDOOR_DEFAULT_CLIENT_SECRET}
CASDOOR_SEP_CLIENT_ID=${CASDOOR_SEP_CLIENT_ID}
CASDOOR_SEP_CLIENT_SECRET=${CASDOOR_SEP_CLIENT_SECRET}
CASDOOR_DEFAULT_ADMIN_PASSWD=${CASDOOR_DEFAULT_ADMIN_PASSWD}
CASDOOR_SEP_ADMIN_PASSWD=${CASDOOR_SEP_ADMIN_PASSWD}
CASDOOR_SEP_SEP_PASSWD=${CASDOOR_SEP_SEP_PASSWD}
SEP_BACKEND_DB_PASSWORD=${SEP_BACKEND_DB_PASSWORD}
SEP_PMM_URL_AUTH_ACCOUNT=${SEP_PMM_URL_AUTH_ACCOUNT}
SEP_PMM_URL_AUTH_TOKEN=${SEP_PMM_URL_AUTH_TOKEN}
GF_SECURITY_ADMIN_PASSWORD=${GF_SECURITY_ADMIN_PASSWORD}
INSTALL_DIR=${ABS_INSTALL_DIR}
EOF

    export SEP_HTTP_PORT SEP_HTTPS_PORT SEP_PMM_PUBLIC_HOST SEP_PMM_PORT SEP_PMM_FRONTEND SEP_IMAGE_NAME SEP_IMAGE_TAG CREATE_PMM_CONTAINER
    export CASDOOR_INIT_JSON_DATA NGINX_CONFIG SEP_COMPOSE_YAML SEP_SETTINGS_YAML
    export -f perform_template_rendering

    spin_or_die points "Rendering templates..." "perform_template_rendering '$ABS_INSTALL_DIR'"
}

generate_files() {
    if [ ! -d "${INSTALL_DIR}" ]; then
        DIR_WAS_CREATED_BY_SCRIPT=1
    fi
    spin_or_die line "Creating directory structure..." "mkdir -p '${INSTALL_DIR}'"
    log_info "Generating configuration and secrets..."
    init_plugin_disable_markers
    generate_secrets_and_render
}

get_engine_command() {
    case "${CONTAINER_ENGINE}" in
        docker)
            echo "docker compose --file ${INSTALL_DIR}/compose.yaml --project-name sep"
            ;;
        podman)
            echo "podman-compose --file ${INSTALL_DIR}/compose.yaml --project-name sep"
            ;;
    esac
}

pull_and_start() {
    CMD=$(get_engine_command)

    if [ "${SEP_IMAGE_NAME%%/*}" = "docker.io" ] && [ "${SEP_IMAGE_NAME}" != "docker.io/library/*" ]; then
        set +o errexit
        if [ "${NO_GUM}" -eq 0 ]; then
             gum spin --spinner globe --title "Pulling SEP image (attempt 1)..." ${CONTAINER_ENGINE} pull "${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}"
        else
             echo "Pulling SEP image (attempt 1)..."
             ${CONTAINER_ENGINE} pull "${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}"
        fi
        PULL_RES=$?
        set -o errexit

        if [ $PULL_RES -ne 0 ]; then
            log_info "Public pull failed. Login required for ${SEP_IMAGE_NAME}."

            EXTRA_ARGS=
            PODMAN_AUTH_FILE=".docker-io-percona-sep"
            SHOULD_DELETE_PODMAN_AUTH_FILE=0
            if [ "${CONTAINER_ENGINE}" = "podman" ]; then
                SHOULD_DELETE_PODMAN_AUTH_FILE=$([ -e "$PODMAN_AUTH_FILE" ] && echo 0 || echo 1)
                EXTRA_ARGS="--authfile=${PODMAN_AUTH_FILE}"
            fi
            if [ -z "${DOCKER_TOKEN}" ]; then
                if [ "${NO_GUM}" -eq 0 ]; then
                     DOCKER_TOKEN=$(gum input --password --placeholder "Docker Token")
                else
                     read -rsp "Docker Token: " DOCKER_TOKEN
                     echo ""
                fi
            fi
            spin_or_die dot "Logging in..." "echo '${DOCKER_TOKEN}' | ${CONTAINER_ENGINE} login --username percona ${EXTRA_ARGS:+$EXTRA_ARGS} --password-stdin '${SEP_IMAGE_NAME%%/*}'"
            spin_or_die globe "Pulling SEP image (attempt 2)..." "${CONTAINER_ENGINE} pull '${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}'"
            ${CONTAINER_ENGINE} logout ${EXTRA_ARGS:+$EXTRA_ARGS} docker.io > /dev/null 2>&1 || true
            ${CONTAINER_ENGINE} logout ${EXTRA_ARGS:+$EXTRA_ARGS} https://index.docker.io/v1/ > /dev/null 2>&1 || true
            if [ "$SHOULD_DELETE_PODMAN_AUTH_FILE" -eq 1 ] && [ -e "$PODMAN_AUTH_FILE" ]; then
                rm -f "$PODMAN_AUTH_FILE"
            fi
        fi
    else
        spin_or_die globe "Pulling SEP image..." "${CONTAINER_ENGINE} pull '${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}'"
    fi

    spin_or_die dot "Creating containers..." "${CMD} up --detach --no-start --remove-orphans"

    if [ "$AUTOSTART" -eq 1 ]; then
        spin_or_die dot "Starting Stack..." "${CMD} start"

        if [ "${NO_GUM}" -eq 0 ]; then
            gum format \
                "## Installation Complete: SEP started!" \
                "To watch logs, run:" \
                "  \`${CMD} logs -f\`" \
                "To stop the stack, run:" \
                "  \`${CMD} down\`"
        else
            echo "## Installation Complete: SEP started!"
            echo "To watch logs, run:"
            echo "${CMD} logs -f"
            echo "To stop the stack, run:"
            echo "${CMD} down"
        fi
    else
        clear_screen
        banner

        if [ "${NO_GUM}" -eq 0 ]; then
            gum format \
                "## Installation Complete!" \
                "To start the stack, run:" \
                "  \`${CMD} start\`" \
                "" \
                "To watch logs, run:" \
                "  \`${CMD} logs -f\`"
        else
            echo "## Installation Complete!"
            echo "To start the stack, run:"
            echo "${CMD} start"
            echo "To watch logs, run:"
            echo "${CMD} logs -f"
        fi
    fi

    echo ""
    if [ "${NO_GUM}" -eq 0 ]; then
        gum style --border rounded --margin "0 1" --padding "1 2" --border-foreground "99" \
            "SEP Access & Credentials"
        gum format << EOF
# Access Interface
> **https://localhost:${SEP_HTTPS_PORT}**

# Credentials
Secrets are stored in: \`${INSTALL_DIR}/.secrets\`

Run the following to retrieve your passwords:
EOF
        echo
        gum format "### Admin User (admin)" | tr -d '\n'
        gum format -t code -l sh "sed -n 's/^CASDOOR_SEP_ADMIN_PASSWD=//p' \"${INSTALL_DIR}/.secrets\""
        gum format "### Standard User (sep)" | tr -d '\n'
        gum format -t code -l sh "sed -n 's/^CASDOOR_SEP_SEP_PASSWD=//p' \"${INSTALL_DIR}/.secrets\""
    else
        echo "=============================="
        echo "   SEP Access & Credentials   "
        echo "=============================="
        echo ""
        echo "Access Interface: https://localhost:${SEP_HTTPS_PORT}"
        echo ""
        echo "Credentials stored in: '${INSTALL_DIR}/.secrets"
        echo "Run the following to retrieve your passwords:"
        echo
        echo "Admin User (admin):"
        echo "sed -n 's/^CASDOOR_SEP_ADMIN_PASSWD=//p' \"${INSTALL_DIR}/.secrets\""
        echo "Standard User (sep):"
        echo "sed -n 's/^CASDOOR_SEP_SEP_PASSWD=//p' \"${INSTALL_DIR}/.secrets\""
    fi
}

################################################################################
# MAIN EXECUTION
################################################################################

parse_args "$@"

if ! ensure_gum; then
    NO_GUM=1
    echo ""
    echo "!!! WARNING: GUM could not be loaded or was disabled. !!!"
    echo "!!! Running in standard text mode.                      !!!"
    echo ""
    sleep 2
fi

check_prereqs

if [ "$NO_INTERACTION" -eq 0 ]; then
    MISSING_PMM_CREDS=0
    [ "$CREATE_PMM_CONTAINER" -eq 0 ] && { [ -z "${SEP_PMM_URL_AUTH_ACCOUNT_USER}" ] || [ -z "${SEP_PMM_URL_AUTH_ACCOUNT_PASS}" ] || [ -z "${SEP_PMM_URL_AUTH_TOKEN:-}" ]; } && MISSING_PMM_CREDS=1

    if [ "$SET_CLI_INSTALL_DIR" -eq 0 ] ||
        [ "$SET_CLI_PLUGINS" -eq 0 ] ||
        [ "$SET_CLI_PMM" -eq 0 ] ||
        [ "$MISSING_PMM_CREDS" -eq 1 ]; then
        get_user_input
    fi

    summary_screen
else
    if [ "$CREATE_PMM_CONTAINER" -eq 0 ]; then
         SEP_PMM_URL_AUTH_ACCOUNT="${SEP_PMM_URL_AUTH_ACCOUNT_USER:-admin}:${SEP_PMM_URL_AUTH_ACCOUNT_PASS:-admin}"
         export SEP_PMM_URL_AUTH_ACCOUNT
    fi
fi

generate_files
pull_and_start
