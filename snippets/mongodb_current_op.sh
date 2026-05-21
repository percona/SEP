#!/usr/bin/env bash

# ---
# title: "MongoDB Current Operations"
# description: "Captures db.currentOp(true) from a MongoDB instance — every in-progress operation, including idle and system operations — for support diagnostics. Filter with --min-secs to keep only long-running operations and --active-only to drop idle connections."
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
#  - name: min-secs
#    type: int
#    label: Minimum seconds running
#    description: Keep only operations whose secs_running is at least this value. 0 includes every operation.
#    default: 0
#    ge: 0
#    le: 86400
#  - name: active-only
#    type: bool
#    label: Active operations only
#    description: Exclude idle connections and idle system operations from the output.
#    default: false
# service_type: mongodb
# alerts:
#   - MongoDBInstanceNotAvailable
#   - MongoDBHighWriteConflict
#   - MongoDBReadWriteQueueHigh
#   - MongoDBHighFlowControl
# ---

# mongodb_current_op.sh
#
# Captures db.currentOp(true) from a MongoDB instance: every in-progress
# operation, including idle connections and idle system operations. This is
# the go-to view for diagnosing long-running queries, blocked writes and
# operations stuck waiting on locks.
#
# db.currentOp(true) can return a very large list on a busy server (roughly one
# entry per connection). Narrow it with --min-secs (keep only operations
# running at least N seconds) and --active-only (drop idle operations).
#
# Authentication is performed with db.auth() over the shell's stdin, so the
# password is not passed to mongosh/mongo on the process command line.
#
# Usage:
#   ./mongodb_current_op.sh [--host=HOST] [--port=PORT] [--user=USER] \
#       [--password=PASS] [--auth-database=DB] [--min-secs=N] [--active-only]

set -euo pipefail

HOST="localhost"
PORT=27017
USER=""
PASSWORD=""
AUTH_DB="admin"
MIN_SECS=0
ACTIVE_ONLY=0

usage() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: $(basename "$0") [OPTIONS]
Capture db.currentOp(true) from a MongoDB instance.

Command line options:

   --host             MongoDB host (default: localhost)
   --port             MongoDB port (default: 27017)
   --user             MongoDB user (provide together with --password)
   --password         MongoDB password (provide together with --user)
   --auth-database    Authentication database (default: admin)
   --min-secs         Keep only operations running at least N seconds
                      (default: 0, i.e. every operation)
   --active-only      Exclude idle connections and idle system operations
   -h, --help         Show this help message
EOS
    exit "${exit_code}"
}

if ! OPTS=$(getopt --options h --longoptions 'host:,port:,user:,password:,auth-database:,min-secs:,active-only,help' -- "$@"); then
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
        --min-secs)
            MIN_SECS="$2"
            shift 2
            ;;
        --active-only)
            ACTIVE_ONLY=1
            shift
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

if ! [[ $MIN_SECS =~ ^[0-9]+$ ]]; then
    echo "Error: --min-secs must be a non-negative integer." >&2
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

# The credentials are not passed to mongosh/mongo on the command line; only the
# connection endpoint is. Authentication happens via db.auth() in the piped script below.
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

# Resolve the --active-only flag to a JavaScript boolean literal.
ACTIVE_ONLY_JS="false"
if [ "$ACTIVE_ONLY" -eq 1 ]; then
    ACTIVE_ONLY_JS="true"
fi

# db.currentOp(true) is filtered client-side. MIN_SECS is a validated integer
# and ACTIVE_ONLY_JS is a literal boolean, so both are safe to inline here.
CURRENTOP_SCRIPT="
var r = db.currentOp(true);
var ops = (r.inprog || []).filter(function (o) {
    if ($ACTIVE_ONLY_JS && !o.active) { return false; }
    if ((o.secs_running || 0) < $MIN_SECS) { return false; }
    return true;
});
JSON.stringify({ count: ops.length, inprog: ops }, null, 2)
"

echo "=== MongoDB Current Operations ==="
echo "MongoDB shell: $MONGO_BIN"
echo "Endpoint: $HOST:$PORT"
echo "Filter: min-secs=$MIN_SECS, active-only=$ACTIVE_ONLY_JS"
echo ""

echo "********* db.currentOp(true) *********"
echo ""
mongo_eval "$CURRENTOP_SCRIPT" 2>&1 ||
    echo "Could not retrieve currentOp."

echo ""
echo "=== Done ==="
