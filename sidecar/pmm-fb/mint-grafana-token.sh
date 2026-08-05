#!/usr/bin/env bash
# Mint a Grafana service-account token in the PMM feature build and wire it into
# this directory's .env as SEP_GRAFANA_TOKEN, which the side-car expands into
# AUTH.PROVIDER.grafana.service_account_token and PMM.API_KEY, then recreate the
# SEP side-car so it picks the token up. A restart would not: it reuses the
# existing container's environment, so the new token would never reach the
# process.
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
need_cmd grep

usage() {
    cat << 'EOF'
mint-grafana-token.sh [OPTIONS]

Create (or reuse) the "sep-fb" Grafana service account in the PMM feature
build, mint a fresh Admin token for it, write the token into .env, and
recreate the sep-sidecar container so it picks up the new environment.

Options:
  -n, --dry-run       Mint nothing; show what would be done
  --no-recreate       Update .env but skip the container recreate
  -h, --help          Show this help

Environment:
  PMM_URL             PMM base URL (default: https://127.0.0.1:8443)
  PMM_ADMIN_USER      Grafana admin user (default: admin)
  PMM_ADMIN_PASSWORD  Grafana admin password (default: admin)

Examples:
  ./mint-grafana-token.sh
  PMM_ADMIN_PASSWORD=secret ./mint-grafana-token.sh --no-recreate
EOF
    exit "${1:-0}"
}

DRY_RUN=0
RECREATE=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h | --help) usage 0 ;;
        -n | --dry-run)
            DRY_RUN=1
            shift
            ;;
        --no-recreate)
            RECREATE=0
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
env_file="${script_dir}/.env"
[[ -f ${env_file} ]] || {
    error ".env not found next to this script: ${env_file}"
    error "Run ./bootstrap.sh first."
    exit 1
}

grafana_api() {
    curl -ksSf -u "${PMM_ADMIN_USER}:${PMM_ADMIN_PASSWORD}" \
        -H 'Content-Type: application/json' "$@"
}

if [[ ${DRY_RUN} -eq 1 ]]; then
    info "[dry-run] Would create/reuse service account '${SA_NAME}' at ${PMM_URL}/graph"
    info "[dry-run] Would mint an Admin token and write it into ${env_file}"
    [[ ${RECREATE} -eq 1 ]] && info "[dry-run] Would recreate the sep-sidecar container"
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
# .env is sourced by bootstrap.sh and parsed by compose, so a token carrying $,
# backticks, spaces, # or quotes would corrupt the line or expand at source time
# and the side-car would come up healthy on the wrong token
[[ ${token} =~ ^glsa_[A-Za-z0-9_]+$ ]] || {
    error "Unexpected token format from Grafana"
    exit 1
}
success "Minted Grafana service-account token (${SA_NAME}, role Admin)"

# Read-then-truncate-write rather than sed -i, so .env keeps the 0600 mode
# bootstrap.sh gave it — it holds every per-deployment secret
if grep -q '^SEP_GRAFANA_TOKEN=' "${env_file}"; then
    # Truncating on a failed or empty read would destroy the other secrets, and
    # unlike pmm.conf they are generated once and cannot be re-derived
    updated="$(sed -E "s|^SEP_GRAFANA_TOKEN=.*|SEP_GRAFANA_TOKEN=${token}|" "${env_file}")" || {
        error "Could not read ${env_file}; leaving it unchanged"
        exit 1
    }
    [[ -n ${updated} ]] || {
        error "Refusing to overwrite ${env_file} with an empty result"
        exit 1
    }
    printf '%s\n' "${updated}" > "${env_file}"
else
    # A hand-edited .env may lack the trailing newline the append needs
    [[ -z $(tail -c1 "${env_file}") ]] || printf '\n' >> "${env_file}"
    printf 'SEP_GRAFANA_TOKEN=%s\n' "${token}" >> "${env_file}"
fi
success "Wrote the token into ${env_file}"

if [[ ${RECREATE} -eq 1 ]]; then
    # Pick whichever engine is actually running the stack (both CLIs may exist).
    # --no-deps leaves pmm-server and its provisioning time alone despite depends_on
    if [[ -n "$(cd "${script_dir}" && docker compose ps -q sep-sidecar 2> /dev/null)" ]]; then
        (cd "${script_dir}" && docker compose up -d --force-recreate --no-deps sep-sidecar)
    elif [[ -n "$(cd "${script_dir}" && podman compose ps -q sep-sidecar 2> /dev/null)" ]]; then
        (cd "${script_dir}" && podman compose up -d --force-recreate --no-deps sep-sidecar)
    else
        info "No running sep-sidecar found; recreate the SEP container manually to apply the token"
        exit 0
    fi
    success "Recreated sep-sidecar"
else
    info "Skipping recreate; recreate the SEP container to apply the token"
fi
