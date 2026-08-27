#!/usr/bin/env bash
# Expand the documented per-deployment inputs into the canonical __-nested
# settings variables, leaving unexported any name a file under SECRETS_DIR
# already supplies. Sourced by entrypoint.sh; kept separate so it can be
# exercised under `env -i` without starting a container.
#
# Assumes the caller's `set -o nounset`, hence ${VAR:-} on every optional read.

# Names lowercased because the settings source matches file names
# case-insensitively; an exact-match lookup here would miss a mounted file and
# then shadow it with a derived export, which outranks every secret file.
# Entries resolving outside the directory are skipped, matching the walk in
# NestedSecretsSettingsSource -- reading one here would suppress an export the
# settings classes then never fill.
declare -A secret_files=()
secrets_root=""
if [[ -n ${SECRETS_DIR:-} && -d ${SECRETS_DIR} ]]; then
    secrets_root="$(readlink -f -- "${SECRETS_DIR}")"
    for secret_entry in "$secrets_root"/*; do
        [[ -f $secret_entry ]] || continue
        [[ "$(readlink -f -- "$secret_entry")" == "$secrets_root"/* ]] || continue
        secret_base="${secret_entry##*/}"
        secret_files["${secret_base,,}"]="$secret_entry"
    done
    unset secret_entry secret_base
fi

# Keyed on the file existing rather than on its contents: pydantic-settings
# resolves an empty secret file to the empty string instead of falling through to
# the next source.
secret_file_supplies() {
    [[ -n ${secret_files["${1,,}"]:-} ]]
}

# Stripped the way the settings source strips it, which `$(<file)` alone is not:
# that trims trailing newlines only.
read_secret_file() {
    local raw
    raw="$(< "${secret_files["${1,,}"]}")"
    raw="${raw#"${raw%%[![:space:]]*}"}"
    printf '%s' "${raw%"${raw##*[![:space:]]}"}"
}

# The script's own resolution order, applied to one canonical name: an explicitly
# set variable, then a mounted file -- left unexported so the settings class reads
# it -- then the derived value.
export_canonical() {
    local name="$1" derived="$2" current
    current="${!name:-}"
    if [[ -n $current ]]; then
        export "$name=$current"
    elif secret_file_supplies "$name"; then
        # Cleared rather than merely left alone: a name inherited as the empty
        # string counts as supplied on the environment side, so leaving it in
        # place would rank it above the file this branch defers to.
        unset "$name"
    else
        export "$name=$derived"
    fi
}

# Settings.SECRET_KEY defaults to secrets.token_urlsafe(32) evaluated at
# class-definition time, so without an explicit value each supervisord child
# resolves a different key -- breaking session-cookie and CSRF validation across
# processes, and giving each process a different HMAC-derived SEP_INTERNAL_TOKEN.
# The one name whose file must hold a value rather than merely exist: the
# settings classes refuse an empty key outright, so admitting one here would
# replace this gate's single actionable line with five crashing children.
if [[ -z ${SECRET_KEY:-} ]]; then
    if [[ -z "$(secret_file_supplies SECRET_KEY && read_secret_file SECRET_KEY)" ]]; then
        echo "[entrypoint] SECRET_KEY is required. Generate one with" \
            "'openssl rand -hex 32' and pass it to the container, or mount it as a" \
            "file named SECRET_KEY under SECRETS_DIR." >&2
        exit 1
    fi
    # Cleared for the same reason export_canonical clears a deferred name: an
    # inherited empty string outranks the file every child then reads.
    unset SECRET_KEY
fi

# The migrate wait loops read SEP_DB_HOST/SEP_DB_PORT below, so a mounted host or
# port has to seed them before their defaults apply -- and seeding all three
# services off it is why a mounted host is not confined to SEP the way a mounted
# password is.
if [[ -z ${SEP__DATABASE__HOST:-} ]] && secret_file_supplies SEP__DATABASE__HOST; then
    SEP_DB_HOST="$(read_secret_file SEP__DATABASE__HOST)"
fi
if [[ -z ${SEP__DATABASE__PORT:-} ]] && secret_file_supplies SEP__DATABASE__PORT; then
    SEP_DB_PORT="$(read_secret_file SEP__DATABASE__PORT)"
fi

# Exported unconditionally: supervisord.conf expands these via %(ENV_...)s, which
# reads supervisord's own environment.
export SEP_DB_HOST="${SEP_DB_HOST:-pmm-server}"
export SEP_DB_PORT="${SEP_DB_PORT:-5432}"

export_canonical SEP__DATABASE__HOST "$SEP_DB_HOST"
export_canonical INVENTORY__DATABASE__HOST "$SEP_DB_HOST"
export_canonical TASKS__DATABASE__HOST "$SEP_DB_HOST"
export_canonical SEP__DATABASE__PORT "$SEP_DB_PORT"
export_canonical INVENTORY__DATABASE__PORT "$SEP_DB_PORT"
export_canonical TASKS__DATABASE__PORT "$SEP_DB_PORT"

# The four guards below skip calling export_canonical -- and so skip its blank
# clear -- whenever their raw input is absent; SEP_INTERNAL_TOKEN, BASE_URL and
# CELERY__BEAT_DBURI have no guard and no export_canonical call at all. A blank
# inherited value on any of these still outranks the file or default below it,
# and for the URL-typed ones an inherited blank fails settings validation
# outright, so all of them are cleared unconditionally before any guard decides.
blank_cleared_names=(
    DATABASE__PASSWORD
    SEP__DATABASE__PASSWORD INVENTORY__DATABASE__PASSWORD TASKS__DATABASE__PASSWORD
    AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN PMM__API_KEY
    PMM__ENDPOINT AUTH__PROVIDER__GRAFANA__ENDPOINT
    TASKS__NOMAD__ENDPOINT
    SEP_INTERNAL_TOKEN BASE_URL
    CELERY__BEAT_DBURI
)
for name in "${blank_cleared_names[@]}"; do
    if [[ -z ${!name:-} ]]; then
        unset "$name"
    fi
done
unset name

# The outer guard stays: without a raw input and without a file, export_canonical
# alone would export the canonical name empty.
if [[ -n ${SEP_DB_PASSWORD:-} ]]; then
    export_canonical SEP__DATABASE__PASSWORD "$SEP_DB_PASSWORD"
    export_canonical INVENTORY__DATABASE__PASSWORD "$SEP_DB_PASSWORD"
    export_canonical TASKS__DATABASE__PASSWORD "$SEP_DB_PASSWORD"
fi

# A function rather than two lines in the guard below because entrypoint.sh calls
# it a second time, with a token minted after this file has finished, and both
# names have to keep resolving from one place.
export_grafana_token() {
    export_canonical AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN "$1"
    export_canonical PMM__API_KEY "$1"
}

if [[ -n ${SEP_GRAFANA_TOKEN:-} ]]; then
    export_grafana_token "$SEP_GRAFANA_TOKEN"
fi

if [[ -n ${SEP_PMM_ENDPOINT:-} ]]; then
    # Trailing slash trimmed so the appended Grafana prefix cannot double it.
    pmm_endpoint="${SEP_PMM_ENDPOINT%/}"
    export_canonical PMM__ENDPOINT "$pmm_endpoint"
    export_canonical AUTH__PROVIDER__GRAFANA__ENDPOINT "${pmm_endpoint}/graph"
fi

if [[ -n ${SEP_NOMAD_ENDPOINT:-} ]]; then
    export_canonical TASKS__NOMAD__ENDPOINT "$SEP_NOMAD_ENDPOINT"
fi
