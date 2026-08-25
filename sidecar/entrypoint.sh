#!/usr/bin/env bash
# Side-car PID 1: expand the per-deployment inputs into canonical settings
# variables, mint the bundled Valkey broker's credential for this container run,
# resolve SEP's Grafana service-account token, then hand off to supervisord.
#
# The credential reaches valkey-server through a generated config file rather
# than a --requirepass flag, and reaches healthcheck.sh by being read back out of
# that file -- a HEALTHCHECK command runs in a fresh process that sees only the
# image's ENV, never what this script exports.
set -o errexit -o nounset -o pipefail

# Resolved from this script rather than written absolute so the start path can be
# exercised outside an image; in the image it is $APP_HOME either way.
app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Sourced first, so a misconfigured container's first log line is the actionable
# message rather than a Valkey mint that was never going to be reached.
# shellcheck source=sidecar/settings-env.sh
. "$app_dir/settings-env.sh"

valkey_conf=/tmp/valkey.conf

valkey_password="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"

# A password in argv is readable by every process in the container's PID
# namespace -- the same population the loopback bind fails to exclude when the
# side-car shares a namespace with PMM, which is the case this guards. umask
# rather than a follow-up chmod so the value is never briefly world-readable.
(
    umask 077
    # /tmp survives a container restart, so a leftover path could be a symlink
    # the redirection would follow -- and umask does not apply to an existing
    # target.
    rm -f "$valkey_conf"
    cat > "$valkey_conf" << EOF
port 6379
bind 127.0.0.1
maxmemory 256mb
maxmemory-policy noeviction
save ""
appendonly no
requirepass ${valkey_password}
EOF
)

# The environment outranks the mounted settings.yaml in the config-priority
# chain, so a profile carrying a password-less broker URL keeps working.
export CELERY__BROKER_URL="redis://:${valkey_password}@127.0.0.1:6379/0"
export CELERY__RESULT_BACKEND="redis://:${valkey_password}@127.0.0.1:6379/1"

# Absorbing the helper's failure is load-bearing under errexit: auth degrading to
# what it does today is survivable, a PID 1 that dies before supervisord is not.
# The value arrives by command substitution for the same reason the Valkey
# password above does -- an argv is readable across the whole PID namespace.
grafana_token="$(python3 "$app_dir/grafana_service_account.py")" || grafana_token=""
if [[ -n $grafana_token ]]; then
    export_grafana_token "$grafana_token"
fi

# The admin pair is more privileged than the token it mints and only the step
# above reads it, so leaving it exported would hand every supervised program a
# Grafana administrator credential for the life of the container.
unset grafana_token GF_SECURITY_ADMIN_USER GF_SECURITY_ADMIN_PASSWORD

exec supervisord -c "$app_dir/supervisord.conf" "$@"
