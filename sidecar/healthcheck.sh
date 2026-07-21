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
not_up="$(supervisorctl -c "$conf" status |
    grep -Ev '\bRUNNING\b' |
    grep -Ev '^migrate-(sep|inventory|tasks)[[:space:]]+EXITED\b' || true)"
if [[ -n $not_up ]]; then
    printf 'unhealthy: program(s) not RUNNING:\n%s\n' "$not_up" >&2
    exit 1
fi

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

if [[ "$(valkey-cli -p 6379 ping 2> /dev/null)" != "PONG" ]]; then
    echo 'unhealthy: valkey broker did not answer PING' >&2
    exit 1
fi

echo 'healthy'
