#!/usr/bin/env bash
# Aggregate container health for the consolidated SEP side-car.
# Exit 0 only if every non-one-shot supervisord program is RUNNING, all three
# migrations completed, all three API /health endpoints return 200, and the
# bundled Valkey broker answers PING.
set -o errexit -o nounset -o pipefail

conf=/home/sep/app/supervisord.conf

# Only the migration one-shots may sit in EXITED; every other program must be
# RUNNING. A failed upgrade also lands in EXITED and is indistinguishable here,
# so completion is asserted separately via the sentinels each one-shot writes.
# Each program is asserted positively rather than by filtering status output, so
# a supervisorctl that cannot reach the socket reports unhealthy instead of
# yielding an empty diff.
status="$(supervisorctl -c "$conf" status || true)"
mapfile -t programs < <(sed -n 's/^\[program:\(.*\)\]$/\1/p' "$conf" | grep -v '^migrate-')
if [[ ${#programs[@]} -eq 0 ]]; then
    echo "unhealthy: no programs declared in $conf" >&2
    exit 1
fi
for prog in "${programs[@]}"; do
    if ! grep -qE "^${prog}[[:space:]]+RUNNING([[:space:]]|$)" <<< "$status"; then
        printf 'unhealthy: %s is not RUNNING:\n%s\n' "$prog" "$status" >&2
        exit 1
    fi
done

for svc in sep inventory tasks; do
    if [[ ! -f /tmp/migrate-$svc.ok ]]; then
        echo "unhealthy: $svc migrations did not complete successfully" >&2
        exit 1
    fi
done

# curl is absent from the slim base, so probe over loopback with urllib instead.
python3 - << 'PY'
import sys
import urllib.request

for port in (9000, 9001, 9002):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as resp:
            if resp.status != 200:
                sys.exit(f"unhealthy: :{port}/health -> HTTP {resp.status}")
    except Exception as exc:
        sys.exit(f"unhealthy: :{port}/health -> {exc}")
PY

# The generated broker config is the only channel for the credential: this runs
# in a fresh process that sees the image's ENV, not what the entrypoint exported.
# REDISCLI_AUTH rather than --pass keeps it out of this probe's own argv.
valkey_conf=/tmp/valkey.conf
REDISCLI_AUTH="$(sed -n 's/^requirepass //p' "$valkey_conf" 2> /dev/null || true)"
if [[ -z $REDISCLI_AUTH ]]; then
    echo "unhealthy: no broker credential in $valkey_conf" >&2
    exit 1
fi
export REDISCLI_AUTH

if [[ "$(valkey-cli -p 6379 ping 2> /dev/null)" != "PONG" ]]; then
    echo 'unhealthy: valkey broker did not answer PING' >&2
    exit 1
fi

echo 'healthy'
