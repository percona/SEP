#!/usr/bin/env bash

# ---
# title: "MongoDB Server Status"
# description: "Captures db.serverStatus() from a MongoDB instance — connections, opcounters, memory, WiredTiger cache and concurrency tickets, network, replication and metrics — as a single snapshot or a timed series of samples for support diagnostics. Use --sections to narrow the output to selected top-level sections."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: host
#    type: str
#    label: MongoDB host
#    description: Hostname or IP of the MongoDB instance. Defaults to localhost.
#    default: localhost
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
#    description: Username for MongoDB authentication. Provide together with the password, or leave both empty if auth is disabled.
#  - name: password
#    type: str
#    label: MongoDB password
#    description: Password for MongoDB authentication. Provide together with the user, or leave both empty if auth is disabled.
#  - name: auth-database
#    type: str
#    label: Authentication database
#    description: Database used for authenticating the user.
#    default: admin
#  - name: iterations
#    type: int
#    label: Iterations
#    description: Number of serverStatus snapshots to capture.
#    default: 1
#    ge: 1
#    le: 1000
#  - name: interval
#    type: int
#    label: Interval
#    description: Seconds to wait between snapshots.
#    default: 1
#    ge: 1
#    le: 3600
#  - name: sections
#    type: str
#    label: Sections
#    description: Comma-separated top-level serverStatus sections to include (e.g. connections,opcounters,globalLock,wiredTiger). Leave empty for the full document.
# service_type: mongodb
# alerts:
#   - MongoDBInstanceNotAvailable
#   - MongoDBHighConnections
#   - MongoDBOpcountersSpike
#   - MongoDBReadWriteQueueHigh
#   - MongoDBTicketExhaustion
# ---

# mongodb_server_status.sh
#
# Captures db.serverStatus() from a MongoDB instance. serverStatus reports the
# server's live metrics: connections, opcounters, memory, WiredTiger cache and
# concurrency tickets, network, locks, replication and assorted metrics.
#
# Many serverStatus fields are counters accumulated since startup, so a single
# snapshot only shows totals. Use --iterations with --interval to capture a
# timed series when you need rates (the deltas between consecutive samples).
#
# serverStatus is a large document; pass --sections with a comma-separated list
# of top-level section names to keep only the parts you need.
#
# Authentication is performed with db.auth() over the shell's stdin, so the
# password is never placed on the process command line.
#
# Usage:
#   ./mongodb_server_status.sh [--host=HOST] [--port=PORT] [--user=USER] \
#       [--password=PASS] [--auth-database=DB] [--iterations=N] [--interval=S] \
#       [--sections=LIST]

set -euo pipefail

HOST="localhost"
PORT=27017
USER=""
PASSWORD=""
AUTH_DB="admin"
ITERATIONS=1
INTERVAL=1
SECTIONS=""

usage() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: $(basename "$0") [OPTIONS]
Capture db.serverStatus() from a MongoDB instance.

Command line options:

   --host             MongoDB host (default: localhost)
   --port             MongoDB port (default: 27017)
   --user             MongoDB user (provide together with --password)
   --password         MongoDB password (provide together with --user)
   --auth-database    Authentication database (default: admin)
   --iterations       Number of snapshots to capture (default: 1)
   --interval         Seconds between snapshots (default: 1)
   --sections         Comma-separated serverStatus sections to include,
                      e.g. connections,opcounters,wiredTiger (default: all)
   -h, --help         Show this help message
EOS
    exit "${exit_code}"
}

if ! OPTS=$(getopt --options h --longoptions 'host:,port:,user:,password:,auth-database:,iterations:,interval:,sections:,help' -- "$@"); then
    echo "Error parsing options" >&2
    usage 1
fi

eval set -- "$OPTS"

while [[ -n $* ]]; do
    case "$1" in
        --host)
            HOST="$2"
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
        --interval)
            INTERVAL="$2"
            shift 2
            ;;
        --sections)
            SECTIONS="$2"
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

# A password with no username (or vice versa) cannot authenticate; reject the
# partial combination instead of silently connecting unauthenticated.
if { [ -n "$USER" ] && [ -z "$PASSWORD" ]; } || { [ -z "$USER" ] && [ -n "$PASSWORD" ]; }; then
    echo "Error: --user and --password must be provided together, or both omitted." >&2
    usage 1
fi

if ! [[ $ITERATIONS =~ ^[0-9]+$ ]] || [[ $ITERATIONS -lt 1 ]]; then
    echo "Error: --iterations must be a positive integer." >&2
    usage 1
fi

if ! [[ $INTERVAL =~ ^[0-9]+$ ]] || [[ $INTERVAL -lt 1 ]]; then
    echo "Error: --interval must be a positive integer." >&2
    usage 1
fi

if [ -n "$SECTIONS" ] && ! [[ $SECTIONS =~ ^[A-Za-z0-9_]+(,[A-Za-z0-9_]+)*$ ]]; then
    echo "Error: --sections must be a comma-separated list of section names" >&2
    echo "(letters, digits and underscores only), e.g. connections,opcounters." >&2
    usage 1
fi

# Pick the MongoDB shell binary, preferring mongosh.
MONGO_BIN=""
if command -v mongosh > /dev/null 2>&1; then
    MONGO_BIN="mongosh"
elif command -v mongo > /dev/null 2>&1; then
    MONGO_BIN="mongo"
fi

if [ -z "$MONGO_BIN" ]; then
    echo "Neither mongosh nor mongo is installed; install one to run this snippet." >&2
    exit 2
fi

# The credentials are never passed on the command line; only the connection
# endpoint is. Authentication happens via db.auth() in the piped script below.
MONGO_ARGS=(--host "$HOST" --port "$PORT")

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
    local auth_prefix=""
    if [ -n "$USER" ] && [ -n "$PASSWORD" ]; then
        local escaped_auth_db escaped_user escaped_password
        escaped_auth_db="$(js_escape "$AUTH_DB")"
        escaped_user="$(js_escape "$USER")"
        escaped_password="$(js_escape "$PASSWORD")"
        auth_prefix="db = db.getSiblingDB('$escaped_auth_db'); if (!db.auth('$escaped_user', '$escaped_password')) { quit(1); }"
    fi
    printf '%s\n%s\n' "$auth_prefix" "$script" |
        "$MONGO_BIN" "${MONGO_ARGS[@]}" --quiet
}

# Build the serverStatus expression: the full document, or only the requested
# top-level sections (plus a few identity fields) when --sections is given.
# SECTIONS is validated above as [A-Za-z0-9_,] so it is safe to inline here.
STATUS_SCRIPT="JSON.stringify(db.serverStatus(), null, 2)"
if [ -n "$SECTIONS" ]; then
    STATUS_SCRIPT="
var s = db.serverStatus();
var keep = '$SECTIONS'.split(',');
var out = {};
['host', 'version', 'process', 'uptime', 'localTime', 'ok'].forEach(function (k) {
    if (s[k] !== undefined) { out[k] = s[k]; }
});
keep.forEach(function (k) {
    if (s[k] !== undefined) { out[k] = s[k]; }
});
JSON.stringify(out, null, 2)
"
fi

echo "=== MongoDB Server Status ==="
echo "MongoDB shell: $MONGO_BIN"
echo "Endpoint: $HOST:$PORT"
echo "Samples: $ITERATIONS (interval ${INTERVAL}s)"
echo "Sections: ${SECTIONS:-all}"
echo ""

for ((i = 1; i <= ITERATIONS; i++)); do
    echo "********* serverStatus sample $i/$ITERATIONS - $(date -u +%FT%TZ) *********"
    echo ""
    mongo_eval "$STATUS_SCRIPT" 2>&1 ||
        echo "Could not retrieve serverStatus."
    echo ""
    if [ "$i" -lt "$ITERATIONS" ]; then
        sleep "$INTERVAL"
    fi
done

echo "=== Done ==="
