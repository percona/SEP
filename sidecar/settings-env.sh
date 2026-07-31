#!/usr/bin/env bash
# Expand the documented per-deployment inputs into the canonical __-nested
# settings variables. Sourced by entrypoint.sh; kept separate so it can be
# exercised under `env -i` without starting a container.
#
# Assumes the caller's `set -o nounset`, hence ${VAR:-} on every optional read.

# Settings.SECRET_KEY defaults to secrets.token_urlsafe(32) evaluated at
# class-definition time, so without an explicit value each supervisord child
# resolves a different key -- breaking session-cookie and CSRF validation across
# processes, and giving each process a different HMAC-derived SEP_INTERNAL_TOKEN.
if [[ -z ${SECRET_KEY:-} ]]; then
    echo "[entrypoint] SECRET_KEY is required. Generate one with" \
        "'openssl rand -hex 32' and pass it to the container." >&2
    exit 1
fi

# Exported unconditionally: supervisord.conf expands these via %(ENV_...)s, which
# reads supervisord's own environment.
export SEP_DB_HOST="${SEP_DB_HOST:-pmm-server}"
export SEP_DB_PORT="${SEP_DB_PORT:-5432}"

# Conditional assignment throughout, so an explicitly-supplied canonical variable
# still wins over the derived one.
: "${SEP__DATABASE__HOST:=${SEP_DB_HOST}}"
: "${INVENTORY__DATABASE__HOST:=${SEP_DB_HOST}}"
: "${TASKS__DATABASE__HOST:=${SEP_DB_HOST}}"
: "${SEP__DATABASE__PORT:=${SEP_DB_PORT}}"
: "${INVENTORY__DATABASE__PORT:=${SEP_DB_PORT}}"
: "${TASKS__DATABASE__PORT:=${SEP_DB_PORT}}"
export SEP__DATABASE__HOST INVENTORY__DATABASE__HOST TASKS__DATABASE__HOST
export SEP__DATABASE__PORT INVENTORY__DATABASE__PORT TASKS__DATABASE__PORT

if [[ -n ${SEP_DB_PASSWORD:-} ]]; then
    : "${SEP__DATABASE__PASSWORD:=${SEP_DB_PASSWORD}}"
    : "${INVENTORY__DATABASE__PASSWORD:=${SEP_DB_PASSWORD}}"
    : "${TASKS__DATABASE__PASSWORD:=${SEP_DB_PASSWORD}}"
    export SEP__DATABASE__PASSWORD INVENTORY__DATABASE__PASSWORD TASKS__DATABASE__PASSWORD
    # Percent-encoded via the environment rather than argv, which is readable by
    # every process in the container's PID namespace.
    beat_userinfo="sep:$(SEP_DB_PASSWORD="${SEP_DB_PASSWORD}" python3 -c \
        'import os, urllib.parse; print(urllib.parse.quote(os.environ["SEP_DB_PASSWORD"], safe=""))')"
else
    beat_userinfo="sep"
fi
# Always derived, so the beat store follows the same host/port input as the profile.
: "${CELERY__BEAT_DBURI:=postgresql://${beat_userinfo}@${SEP_DB_HOST}:${SEP_DB_PORT}/sep}"
export CELERY__BEAT_DBURI

if [[ -n ${SEP_GRAFANA_TOKEN:-} ]]; then
    : "${AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN:=${SEP_GRAFANA_TOKEN}}"
    : "${PMM__API_KEY:=${SEP_GRAFANA_TOKEN}}"
    export AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN PMM__API_KEY
fi

if [[ -n ${SEP_PMM_ENDPOINT:-} ]]; then
    : "${PMM__ENDPOINT:=${SEP_PMM_ENDPOINT}}"
    : "${AUTH__PROVIDER__GRAFANA__ENDPOINT:=${SEP_PMM_ENDPOINT}/graph}"
    export PMM__ENDPOINT AUTH__PROVIDER__GRAFANA__ENDPOINT
fi

if [[ -n ${SEP_NOMAD_ENDPOINT:-} ]]; then
    : "${TASKS__NOMAD__ENDPOINT:=${SEP_NOMAD_ENDPOINT}}"
    export TASKS__NOMAD__ENDPOINT
fi
