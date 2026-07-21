#!/usr/bin/env bash
# Aggregate container health for the consolidated SEP side-car.
# Exit 0 only if every non-one-shot supervisord program is RUNNING, all three API
# /health endpoints return 200, and the bundled Valkey broker answers PING.
set -o errexit -o nounset -o pipefail

conf=/home/sep/app/supervisord.conf

# One-shot migrations legitimately end EXITED(0); anything else must be RUNNING.
not_up="$(supervisorctl -c "$conf" status | grep -Ev '\bRUNNING\b|\bEXITED\b' || true)"
if [[ -n $not_up ]]; then
    printf 'unhealthy: program(s) not RUNNING/EXITED:\n%s\n' "$not_up" >&2
    exit 1
fi

# curl is absent from the slim base, so probe over loopback with urllib instead.
python3 - << 'PY'
import sys
import urllib.request

for port in (9000, 9001, 9002):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
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
