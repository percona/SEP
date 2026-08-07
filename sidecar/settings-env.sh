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
    elif ! secret_file_supplies "$name"; then
        export "$name=$derived"
    fi
}

# Settings.SECRET_KEY defaults to secrets.token_urlsafe(32) evaluated at
# class-definition time, so without an explicit value each supervisord child
# resolves a different key -- breaking session-cookie and CSRF validation across
# processes, and giving each process a different HMAC-derived SEP_INTERNAL_TOKEN.
if [[ -z ${SECRET_KEY:-} ]] && ! secret_file_supplies SECRET_KEY; then
    echo "[entrypoint] SECRET_KEY is required. Generate one with" \
        "'openssl rand -hex 32' and pass it to the container, or mount it as a" \
        "file named SECRET_KEY under SECRETS_DIR." >&2
    exit 1
fi

# Seeded from the file only when the canonical variable is unset, since an
# explicit one shadows the file and the wait loops must follow the value in force.
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

# The outer guard stays: without a raw input and without a file, export_canonical
# alone would export the canonical name empty.
if [[ -n ${SEP_DB_PASSWORD:-} ]]; then
    export_canonical SEP__DATABASE__PASSWORD "$SEP_DB_PASSWORD"
    export_canonical INVENTORY__DATABASE__PASSWORD "$SEP_DB_PASSWORD"
    export_canonical TASKS__DATABASE__PASSWORD "$SEP_DB_PASSWORD"
fi

# Resolved through the same order the canonical exports follow, so the beat store
# and SEP__DATABASE__PASSWORD cannot disagree about which password is in force.
sep_db_password="${SEP__DATABASE__PASSWORD:-}"
if [[ -z $sep_db_password ]]; then
    if secret_file_supplies SEP__DATABASE__PASSWORD; then
        sep_db_password="$(read_secret_file SEP__DATABASE__PASSWORD)"
    else
        sep_db_password="${SEP_DB_PASSWORD:-}"
    fi
fi

if [[ -n ${CELERY__BEAT_DBURI:-} ]]; then
    export CELERY__BEAT_DBURI
elif ! secret_file_supplies CELERY__BEAT_DBURI; then
    # Deriving puts a file-supplied password back into the environment inside the
    # URI. Refusing to derive is worse -- celery-beat would get a password-less
    # URI -- so a mounted CELERY__BEAT_DBURI is the deployment's way out.
    if [[ -n $sep_db_password ]]; then
        # Percent-encoded via the environment rather than argv, which is readable
        # by every process in the container's PID namespace.
        beat_userinfo="sep:$(SEP_BEAT_PASSWORD="$sep_db_password" python3 -c \
            'import os, urllib.parse; print(urllib.parse.quote(os.environ["SEP_BEAT_PASSWORD"], safe=""))')"
    else
        beat_userinfo="sep"
    fi
    export CELERY__BEAT_DBURI="postgresql://${beat_userinfo}@${SEP_DB_HOST}:${SEP_DB_PORT}/sep"
fi

if [[ -n ${SEP_GRAFANA_TOKEN:-} ]]; then
    export_canonical AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN "$SEP_GRAFANA_TOKEN"
    export_canonical PMM__API_KEY "$SEP_GRAFANA_TOKEN"
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
