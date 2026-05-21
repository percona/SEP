#!/usr/bin/env bash

# ---
# title: "MongoDB Sharding Status"
# description: "Runs sh.status() against a MongoDB mongos router to capture the sharded-cluster topology — shards, databases, sharded collections, chunk distribution and balancer state — for support diagnostics. Run it against a mongos."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: host
#    type: str
#    label: MongoDB host
#    description: Hostname or IP of the mongos router. Defaults to localhost.
#    default: localhost
#  - name: port
#    type: int
#    label: MongoDB port
#    description: TCP port of the mongos router.
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
# service_type: mongodb
# alerts:
#   - MongoDBChunksImbalance
#   - MongoDBInstanceNotAvailable
# ---

# mongodb_sharding_status.sh
#
# Captures sh.status() from a MongoDB mongos router, matching the
# "MongoDB shards" data-collection checklist used by Percona Support.
# sh.status() reports the cluster's shards, databases, sharded collections,
# chunk distribution per shard and the balancer state.
#
# Authentication is performed with db.auth() over the shell's stdin, so the
# password is never placed on the process command line.
#
# sh.status() is only meaningful against a mongos; run this on the router.
# Host-level diagnostics for the config server and shard primaries are
# collected separately with mongodb_replica_set_collect.sh.
#
# Usage:
#   ./mongodb_sharding_status.sh [--host=HOST] [--port=PORT] [--user=USER] \
#       [--password=PASS] [--auth-database=DB]

set -euo pipefail

HOST="localhost"
PORT=27017
USER=""
PASSWORD=""
AUTH_DB="admin"

usage() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: $(basename "$0") [OPTIONS]
Capture sh.status() from a MongoDB mongos router.

Command line options:

   --host             mongos host (default: localhost)
   --port             mongos port (default: 27017)
   --user             MongoDB user
   --password         MongoDB password
   --auth-database    Authentication database (default: admin)
   -h, --help         Show this help message
EOS
    exit "${exit_code}"
}

if ! OPTS=$(getopt --options h --longoptions 'host:,port:,user:,password:,auth-database:,help' -- "$@"); then
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

echo "=== MongoDB Sharding Status ==="
echo "MongoDB shell: $MONGO_BIN"
echo "Endpoint: $HOST:$PORT"
echo ""

echo "********* Endpoint check *********"
echo ""
# A mongos router answers isMaster with msg == 'isdbgrid'.
mongo_eval "
var info = db.runCommand({ isMaster: 1 });
if (info.msg === 'isdbgrid') {
    print('Connected to a mongos router; sh.status() applies.');
} else {
    print('WARNING: this endpoint is not a mongos router.');
    print('sh.status() only applies to a sharded cluster; the output below may be an error.');
}
" 2>&1 || echo "Could not determine the endpoint role."

echo ""
echo "********* sh.status() *********"
echo ""
mongo_eval "sh.status()" 2>&1 || echo "Could not retrieve sh.status()."

echo ""
echo "=== Done ==="
