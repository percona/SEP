#!/usr/bin/env bash
# Invalidate the named schema steps' sentinels ahead of a supervisorctl re-run.
#
# entrypoint.sh clears every sentinel before supervisord spawns anything, but a
# `supervisorctl restart` never re-enters PID 1. Each one-shot still removes its
# own sentinel, only once it has been spawned -- and supervisorctl starts the
# named programs one at a time, each API blocking for its startsecs, so a gate
# can poll before that removal and release its app on the previous run's marker.
# Clearing before the restart leaves nothing stale to observe, whatever order the
# programs start in.
#
# Every name is checked before anything is removed, so a typo never leaves some
# sentinels cleared and a restart racing on the rest. Names are matched whole: a
# step is its bare name, the one wait_for_schema.sh takes, not its program name.
set -o errexit -o nounset -o pipefail

readonly SCHEMA_STEPS=(extensions inventory tasks beat)

is_schema_step() {
    local known
    for known in "${SCHEMA_STEPS[@]}"; do
        [[ $1 == "$known" ]] && return 0
    done
    return 1
}

if [[ $# -eq 0 ]]; then
    echo "usage: ${0##*/} <schema-step>..." >&2
    exit 2
fi

for step in "$@"; do
    if ! is_schema_step "$step"; then
        echo "[clear_sentinels] unknown schema step '$step'; expected one of: ${SCHEMA_STEPS[*]}" >&2
        exit 2
    fi
done

for step in "$@"; do
    rm -f "/tmp/migrate-$step.ok"
done
echo "[clear_sentinels] cleared: $*"
