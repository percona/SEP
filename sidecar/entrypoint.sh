#!/usr/bin/env bash
# Side-car PID 1: mint the bundled Valkey broker's credential for this container
# run, then hand off to supervisord.
#
# The credential reaches valkey-server through a generated config file rather
# than a --requirepass flag, and reaches healthcheck.sh by being read back out of
# that file -- a HEALTHCHECK command runs in a fresh process that sees only the
# image's ENV, never what this script exports.
set -o errexit -o nounset -o pipefail

valkey_conf=/tmp/valkey.conf

# openssl is absent from the slim base; python3 runs the SEP services themselves.
valkey_password="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"

# A password in argv is readable by every process in the container's PID
# namespace -- the same population the loopback bind fails to exclude when the
# side-car shares a namespace with PMM, which is the case this guards. umask
# rather than a follow-up chmod so the value is never briefly world-readable.
(
    umask 077
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

exec supervisord -c /home/sep/app/supervisord.conf
