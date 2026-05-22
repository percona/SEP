#!/usr/bin/env bash

# ---
# title: "MongoDB Server Build Info"
# description: "Captures db.serverBuildInfo() from a MongoDB instance — server version and git revision, OpenSSL build, memory allocator, JavaScript engine, enabled modules and build environment — for support diagnostics."
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
# service_type: mongodb
# alerts:
#   - MongoDBInstanceNotAvailable
# ---

# mongodb_server_build_info.sh
#
# Captures db.serverBuildInfo() from a MongoDB instance: the server version and
# git revision, the OpenSSL build, the memory allocator, the JavaScript engine,
# enabled modules and the build environment. This pins down exactly which build
# is running when triaging version-specific bugs and behaviour.
#
# Authentication is performed with db.auth() over the shell's stdin, so the
# password is never placed on the process command line.
#
# Usage:
#   ./mongodb_server_build_info.sh [--host=HOST] [--port=PORT] [--user=USER] \
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
Capture db.serverBuildInfo() from a MongoDB instance.

Command line options:

   --host             MongoDB host (default: localhost)
   --port             MongoDB port (default: 27017)
   --user             MongoDB user (provide together with --password)
   --password         MongoDB password (provide together with --user)
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

# A password with no username (or vice versa) cannot authenticate; reject the
# partial combination instead of silently connecting unauthenticated.
if { [ -n "$USER" ] && [ -z "$PASSWORD" ]; } || { [ -z "$USER" ] && [ -n "$PASSWORD" ]; }; then
    echo "Error: --user and --password must be provided together, or both omitted." >&2
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

echo "=== MongoDB Server Build Info ==="
echo "MongoDB shell: $MONGO_BIN"
echo "Endpoint: $HOST:$PORT"
echo ""

echo "********* db.serverBuildInfo() *********"
echo ""
mongo_eval "JSON.stringify(db.serverBuildInfo(), null, 2)" 2>&1 ||
    echo "Could not retrieve serverBuildInfo."

echo ""
echo "=== Done ==="
