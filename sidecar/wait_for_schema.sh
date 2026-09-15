#!/usr/bin/env bash
# Hold a side-car API program until every schema step has published its sentinel.
#
# supervisord orders its spawn calls by priority but waits for no readiness -- it
# has no depends_on -- so the priority-20 API programs are spawned in the same
# tick as the priority-10 schema one-shots whose tables they read on startup.
# This runs immediately before each API command, joined with `&&`: a step that
# never completed means the app would fail on the tables it is waiting for, so a
# spent budget must not release it. That is the deliberate inverse of
# wait_for_api.py, whose `;` exists so beat starts whatever its gate reports.
#
# Sentinels rather than a database probe: what an API needs is not a reachable
# server but an applied schema, and the sentinel is the only thing that
# distinguishes a completed one-shot from a failed one, both of which end EXITED.
set -o errexit -o nounset -o pipefail

# A constant, not a deployment input. Comparable to the tolerance the API
# programs already carry (startretries=30 x startsecs=8) and well past the
# HEALTHCHECK start-period, so the container is reported unhealthy long before
# the gate gives up.
readonly WAIT_BUDGET_SECONDS=300
readonly POLL_INTERVAL_SECONDS=1
readonly LOG_INTERVAL_SECONDS=10

if [[ $# -eq 0 ]]; then
    echo "usage: ${0##*/} <schema-step>..." >&2
    exit 2
fi

# Names the still-missing steps, space separated, so the caller can both test for
# emptiness and log what it is waiting for.
missing_steps() {
    local step
    local missing=""
    for step in "$@"; do
        [[ -f /tmp/migrate-$step.ok ]] || missing+="${missing:+ }$step"
    done
    printf '%s' "$missing"
}

deadline=$((SECONDS + WAIT_BUDGET_SECONDS))
next_log=$SECONDS

while true; do
    missing="$(missing_steps "$@")"
    if [[ -z $missing ]]; then
        exit 0
    fi
    if ((SECONDS >= deadline)); then
        echo "[wait_for_schema] gave up after ${WAIT_BUDGET_SECONDS}s waiting for: $missing" >&2
        exit 1
    fi
    if ((SECONDS >= next_log)); then
        echo "[wait_for_schema] waiting for: $missing"
        next_log=$((SECONDS + LOG_INTERVAL_SECONDS))
    fi
    sleep "$POLL_INTERVAL_SECONDS"
done
