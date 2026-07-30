#!/usr/bin/env bash
# Mint a Grafana service-account token in the PMM feature build and wire it
# into this directory's settings.yaml (AUTH.PROVIDER.grafana.service_account_token
# and PMM.API_KEY), then restart the SEP side-car so it picks the token up.
# Optional: the PMM UI's SEP pages work without it (interim internal-token
# auth); the token enables SEP-side Grafana auth and the PMM syncer.

set -o nounset
set -o pipefail

if [[ ${DEBUG:-0} == "1" ]]; then
    set -o xtrace
fi

error() { printf '✗ %s\n' "$*" >&2; }
success() { printf '✓ %s\n' "$*" >&2; }
info() { printf 'ℹ %s\n' "$*" >&2; }
debug() { [[ ${DEBUG:-0} == "1" ]] && printf '[DEBUG] %s\n' "$*" >&2 || true; }

need_cmd() {
    command -v "$1" > /dev/null 2>&1 || {
        error "Missing required command: $1"
        exit 2
    }
}

need_cmd curl
need_cmd jq
need_cmd sed

usage() {
    cat << 'EOF'
mint-grafana-token.sh [OPTIONS]

Create (or reuse) the "sep-fb" Grafana service account in the PMM feature
build, mint a fresh Admin token for it, write the token into settings.yaml,
and restart the sep-sidecar container.

Options:
  -n, --dry-run       Mint nothing; show what would be done
  --no-restart        Update settings.yaml but skip the container restart
  -h, --help          Show this help

Environment:
  PMM_URL             PMM base URL (default: https://127.0.0.1:8443)
  PMM_ADMIN_USER      Grafana admin user (default: admin)
  PMM_ADMIN_PASSWORD  Grafana admin password (default: admin)

Examples:
  ./mint-grafana-token.sh
  PMM_ADMIN_PASSWORD=secret ./mint-grafana-token.sh --no-restart
EOF
    exit "${1:-0}"
}

DRY_RUN=0
RESTART=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h | --help) usage 0 ;;
        -n | --dry-run)
            DRY_RUN=1
            shift
            ;;
        --no-restart)
            RESTART=0
            shift
            ;;
        -*)
            error "Unknown option: $1"
            usage 2
            ;;
        *)
            error "Unexpected argument: $1"
            usage 2
            ;;
    esac
done

PMM_URL="${PMM_URL:-https://127.0.0.1:8443}"
PMM_ADMIN_USER="${PMM_ADMIN_USER:-admin}"
PMM_ADMIN_PASSWORD="${PMM_ADMIN_PASSWORD:-admin}"
SA_NAME="sep-fb"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
settings_file="${script_dir}/settings.yaml"
[[ -f ${settings_file} ]] || {
    error "settings.yaml not found next to this script: ${settings_file}"
    exit 1
}

grafana_api() {
    curl -ksSf -u "${PMM_ADMIN_USER}:${PMM_ADMIN_PASSWORD}" \
        -H 'Content-Type: application/json' "$@"
}

if [[ ${DRY_RUN} -eq 1 ]]; then
    info "[dry-run] Would create/reuse service account '${SA_NAME}' at ${PMM_URL}/graph"
    info "[dry-run] Would mint an Admin token and write it into ${settings_file}"
    [[ ${RESTART} -eq 1 ]] && info "[dry-run] Would restart the sep-sidecar container"
    exit 0
fi

sa_id="$(grafana_api -X POST "${PMM_URL}/graph/api/serviceaccounts" \
    -d "{\"name\": \"${SA_NAME}\", \"role\": \"Admin\"}" 2> /dev/null | jq -r '.id // empty')"
if [[ -z ${sa_id} ]]; then
    debug "create returned no id; looking up existing service account"
    sa_id="$(grafana_api "${PMM_URL}/graph/api/serviceaccounts/search?query=${SA_NAME}" |
        jq -r --arg name "${SA_NAME}" \
            '.serviceAccounts[] | select(.name == $name) | .id' | head -1)" || true
fi
[[ -n ${sa_id} ]] || {
    error "Could not create or find the '${SA_NAME}' service account at ${PMM_URL}/graph"
    error "Is pmm-server up (compose up -d; first boot takes a couple of minutes)?"
    exit 1
}
debug "service account id: ${sa_id}"

token="$(grafana_api -X POST "${PMM_URL}/graph/api/serviceaccounts/${sa_id}/tokens" \
    -d "{\"name\": \"${SA_NAME}-$(date +%s)\"}" | jq -r '.key // empty')"
[[ -n ${token} ]] || {
    error "Token creation failed for service account ${sa_id}"
    exit 1
}
success "Minted Grafana service-account token (${SA_NAME}, role Admin)"

sed -E -i "s|(service_account_token:) glsa_[A-Za-z0-9_]+|\1 ${token}|; s|(API_KEY:) glsa_[A-Za-z0-9_]+|\1 ${token}|" \
    "${settings_file}"
success "Wrote the token into ${settings_file}"

if [[ ${RESTART} -eq 1 ]]; then
    # Pick whichever engine is actually running the stack (both CLIs may exist)
    if [[ -n "$(cd "${script_dir}" && docker compose ps -q sep-sidecar 2> /dev/null)" ]]; then
        (cd "${script_dir}" && docker compose restart sep-sidecar)
    elif [[ -n "$(cd "${script_dir}" && podman compose ps -q sep-sidecar 2> /dev/null)" ]]; then
        (cd "${script_dir}" && podman compose restart sep-sidecar)
    else
        info "No running sep-sidecar found; restart the SEP container manually to apply the token"
        exit 0
    fi
    success "Restarted sep-sidecar"
else
    info "Skipping restart; restart the SEP container to apply the token"
fi
