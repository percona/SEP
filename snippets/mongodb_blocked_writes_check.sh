#!/usr/bin/env bash

# ---
# title: "MongoDB Blocked Writes Check"
# description: "Periodically samples pt-summary, MongoDB diagnostics (serverStatus, currentOp, mongostat) and OS metrics (vmstat, iostat, mpstat, sar, top) to a destination directory while writes appear blocked. Stop by creating an 'exit-percona-monitor' marker file in the destination."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: dest
#    type: str
#    label: Destination directory
#    description: Directory where samples and pt-summary output are stored.
#    default: /tmp/mongodb-diagnostics
#    pattern: ^/[A-Za-z0-9._/-]+$
#  - name: port
#    type: int
#    label: MongoDB port
#    description: TCP port of the MongoDB instance.
#    default: 27017
#    ge: 1
#    le: 65535
#  - name: user
#    type: str
#    label: MongoDB user
#    description: Username for MongoDB authentication. Leave empty if auth is disabled.
#  - name: password
#    type: str
#    label: MongoDB password
#    description: Password for MongoDB authentication. Leave empty if auth is disabled.
#  - name: auth-database
#    type: str
#    label: Authentication database
#    description: Database used for authenticating the user.
#    default: admin
#  - name: iterations
#    type: int
#    label: Iterations
#    description: How many sample cycles to run before exiting.
#    default: 3
#    ge: 1
#    le: 1440
#  - name: sleep
#    type: int
#    label: Sleep between iterations
#    description: Seconds to sleep between sample cycles.
#    default: 30
#    ge: 1
#    le: 3600
#  - name: retention-days
#    type: int
#    label: Sample retention (days)
#    description: Files in the destination older than this are purged at the end of each cycle.
#    default: 3
#    ge: 1
#    le: 365
# atw:
#  - WRITES_ARE_BLOCKED
#  - NOT_RESPONDING
#  - OVERALL_SLOWNESS
#  - TEMPORARY_STALLS
# service_type: mongodb
# alerts:
#   - MongoDBHighWriteConflict
#   - MongoDBHighFlowControl
# ---

# Usage:
#   ./mongodb_blocked_writes_check.sh [--dest=DIR] [--port=PORT] [--user=USER] \
#       [--password=PASS] [--auth-database=DB] [--iterations=N] [--sleep=SECS] \
#       [--retention-days=DAYS]
#
# Stop early by creating the marker file in the destination directory:
#   touch /tmp/mongodb-diagnostics/exit-percona-monitor

set -euo pipefail

DEST="/tmp/mongodb-diagnostics"
PORT=27017
USER=""
PASSWORD=""
AUTH_DB="admin"
ITERATIONS=3
SLEEP_SECS=30
RETENTION_DAYS=3

usage() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: $(basename "$0") [OPTIONS]
Sample MongoDB and OS diagnostics into a destination directory.

Command line options:

   --dest               Destination directory (default: /tmp/mongodb-diagnostics)
   --port               MongoDB port (default: 27017)
   --user               MongoDB user
   --password           MongoDB password
   --auth-database      Authentication database (default: admin)
   --iterations         Number of sample cycles (default: 3)
   --sleep              Seconds to sleep between cycles (default: 30)
   --retention-days     Purge samples older than this at each cycle (default: 3)
   -h, --help           Show this help message

Stop early by creating the marker file in the destination directory:
   touch <dest>/exit-percona-monitor
EOS
    exit "${exit_code}"
}

if ! OPTS=$(getopt --options h --longoptions 'dest:,port:,user:,password:,auth-database:,iterations:,sleep:,retention-days:,help' -- "$@"); then
    echo "Error parsing options" >&2
    usage 1
fi

eval set -- "$OPTS"

while [[ -n $* ]]; do
    case "$1" in
        --dest)
            DEST="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --user)
            USER="$2"
            shift 2
            ;;
        --password)
            PASSWORD="$2"
            shift 2
            ;;
        --auth-database)
            AUTH_DB="$2"
            shift 2
            ;;
        --iterations)
            ITERATIONS="$2"
            shift 2
            ;;
        --sleep)
            SLEEP_SECS="$2"
            shift 2
            ;;
        --retention-days)
            RETENTION_DAYS="$2"
            shift 2
            ;;
        -h | --help) usage ;;
        --)
            shift
            break
            ;;
        *)
            echo "Unrecognized option '$1'" >&2
            usage 1
            ;;
    esac
done

mkdir -p "$DEST"

# Pick the MongoDB shell binary, preferring mongosh.
MONGO_BIN=""
if command -v mongosh > /dev/null 2>&1; then
    MONGO_BIN="mongosh"
elif command -v mongo > /dev/null 2>&1; then
    MONGO_BIN="mongo"
fi

MONGO_ARGS=(--port "$PORT")
if [ -n "$USER" ]; then
    MONGO_ARGS+=(-u "$USER" --authenticationDatabase "$AUTH_DB")
fi

js_escape() {
    local value="$1"
    value=${value//\\/\\\\}
    value=${value//\'/\\\'}
    value=${value//$'\n'/\\n}
    value=${value//$'\r'/\\r}
    value=${value//$'\t'/\\t}
    printf '%s' "$value"
}

mongo_eval() {
    local script="$1"
    local outfile="$2"
    local auth_prefix=""
    if [ -z "$MONGO_BIN" ]; then
        echo "Neither mongosh nor mongo is installed; skipping: $outfile" > "$outfile"
        return
    fi
    if [ -n "$USER" ] && [ -n "$PASSWORD" ]; then
        local escaped_auth_db escaped_user escaped_password
        escaped_auth_db="$(js_escape "$AUTH_DB")"
        escaped_user="$(js_escape "$USER")"
        escaped_password="$(js_escape "$PASSWORD")"
        auth_prefix="db = db.getSiblingDB('$escaped_auth_db'); if (!db.auth('$escaped_user', '$escaped_password')) { quit(1); }"
    fi
    printf '%s\n%s\n' "$auth_prefix" "$script" |
        "$MONGO_BIN" "${MONGO_ARGS[@]}" --quiet > "$outfile" 2>&1 || true
}

run_if_available() {
    local cmd="$1"
    local outfile="$2"
    shift 2
    if command -v "$cmd" > /dev/null 2>&1; then
        "$cmd" "$@" > "$outfile" 2>&1 || true
    else
        echo "$cmd is not installed; skipping" > "$outfile"
    fi
}

echo "Destination: $DEST"
echo "MongoDB shell: ${MONGO_BIN:-<none>}"
echo "Iterations: $ITERATIONS  Sleep: ${SLEEP_SECS}s  Retention: ${RETENTION_DAYS}d"
echo "Stop early: touch $DEST/exit-percona-monitor"
echo ""

# ----- One-shot captures -----

if command -v pt-summary > /dev/null 2>&1; then
    pt-summary > "$DEST/pt-summary.out" 2>&1 || true
else
    echo "pt-summary is not installed; install percona-toolkit to enable this capture" \
        > "$DEST/pt-summary.out"
fi

mongo_eval "JSON.stringify(db.adminCommand({ getParameter: '*' }), null, 2)" \
    "$DEST/getParameter.out"
mongo_eval "JSON.stringify(db.adminCommand({ getCmdLineOpts: 1 }), null, 2)" \
    "$DEST/getCmdLineOpts.out"

run_if_available dmesg "$DEST/dmesg"
run_if_available dmesg "$DEST/dmesg_t" -T
run_if_available journalctl "$DEST/journalctl.out" -a --no-pager
run_if_available sysctl "$DEST/sysctl.out" -a

# ----- Sampling loop -----

for ((i = 1; i <= ITERATIONS; i++)); do
    if [ -f "$DEST/exit-percona-monitor" ]; then
        echo "Stop marker found at $DEST/exit-percona-monitor; exiting loop."
        break
    fi

    d=$(date +%F_%H-%M-%S)
    echo "[$d] iteration $i/$ITERATIONS"

    run_if_available netstat "$DEST/${d}-netstat_s" -s &
    (
        if command -v ps > /dev/null 2>&1; then
            ps faux > "$DEST/${d}-ps" 2>&1 || true

            if [ -n "$PASSWORD" ] && command -v sed > /dev/null 2>&1; then
                sed -i -E \
                    -e 's/(-p)[[:space:]]+[^[:space:]]+/\1 [REDACTED]/g' \
                    -e 's/(--password)=[^[:space:]]+/\1=[REDACTED]/g' \
                    -e 's/(--password)[[:space:]]+[^[:space:]]+/\1 [REDACTED]/g' \
                    "$DEST/${d}-ps" || true
            fi
        else
            echo "ps is not installed; skipping" > "$DEST/${d}-ps"
        fi
    ) &
    run_if_available pidstat "$DEST/${d}-pidstat_d" -d 1 60 &
    run_if_available pidstat "$DEST/${d}-pidstat_u" -u 1 60 &
    run_if_available top "$DEST/${d}-top" -bn1 &
    run_if_available vmstat "$DEST/${d}-vmstat" 1 10 &
    run_if_available iostat "$DEST/${d}-iostat" -dx 1 10 &
    run_if_available mpstat "$DEST/${d}-mpstat" -P ALL 1 10 &
    run_if_available sar "$DEST/${d}-sar_dev" -n DEV 1 10 &
    run_if_available sar "$DEST/${d}-sar_tcp" -n TCP,ETCP 1 10 &

    if command -v mongostat > /dev/null 2>&1; then

        MONGOSTAT_ARGS=("${MONGO_ARGS[@]}")
        if [ -n "$PASSWORD" ]; then
            MONGOSTAT_ARGS+=(-p "$PASSWORD")
        fi
        (mongostat "${MONGOSTAT_ARGS[@]}" --rowcount=1 > "$DEST/${d}-mongostat" 2>&1 || true) &
    else
        echo "mongostat not installed" > "$DEST/${d}-mongostat" &
    fi

    mongo_eval "JSON.stringify(db.adminCommand({ currentOp: true }), null, 2)" \
        "$DEST/${d}-currentOp.out" &

    (
        for _ in $(seq 1 10); do
            mongo_eval "JSON.stringify(db.serverStatus(), null, 2)" \
                /dev/stdout >> "$DEST/${d}-mongo-serverStatus" || true
            sleep 1
        done
    ) &

    wait || true

    find "$DEST" -mtime "+${RETENTION_DAYS}" -type f \
        ! -name 'purge.log' ! -name 'exit-percona-monitor' \
        -delete -print >> "$DEST/purge.log" 2>&1 || true

    if [ "$i" -lt "$ITERATIONS" ]; then
        sleep "$SLEEP_SECS"
    fi
done

echo "Done. Samples are in $DEST"
