#!/usr/bin/env bash

# ---
# title: "pt-mongodb-summary"
# description: "Runs pt-mongodb-summary against a MongoDB instance to produce a one-page diagnostic summary: build and host info, running operations, security, oplog, replica set and — for a sharded cluster — cluster-wide and per-shard balancer information. Extra arguments after -- are forwarded to pt-mongodb-summary."
# allow_extra_args: true
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
#  - name: output-format
#    type: str
#    label: Output format
#    description: Report output format produced by pt-mongodb-summary.
#    default: text
#    choices:
#      - text
#      - json
# service_type: mongodb
# alerts:
#   - MongoDBInstanceNotAvailable
#   - MongoDBReplicaState
#   - MongoDBNoPrimary
# ---

# mongodb_pt_summary.sh
#
# Runs pt-mongodb-summary, the MongoDB counterpart of pt-mysql-summary, to
# capture a one-page diagnostic summary of a MongoDB instance: build/version,
# host hardware, running operations, security, oplog, replica set and -- for a
# sharded cluster -- cluster-wide and per-shard balancer information.
#
# pt-mongodb-summary ships with the percona-toolkit package.
#
# Note: pt-mongodb-summary has no stdin or environment mechanism for the
# password, so when --password is set it is passed on the tool's command line
# and is briefly visible in the process list while the tool runs.
#
# Usage:
#   ./mongodb_pt_summary.sh [--host=HOST] [--port=PORT] [--user=USER] \
#       [--password=PASS] [--auth-database=DB] [--output-format=text|json] \
#       [-- extra pt-mongodb-summary args...]

set -euo pipefail

HOST="localhost"
PORT=27017
USER=""
PASSWORD=""
AUTH_DB="admin"
OUTPUT_FORMAT="text"

usage() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: $(basename "$0") [OPTIONS] [-- extra pt-mongodb-summary args...]
Run pt-mongodb-summary against a MongoDB instance.

Command line options:

   --host             MongoDB host (default: localhost)
   --port             MongoDB port (default: 27017)
   --user             MongoDB user
   --password         MongoDB password
   --auth-database    Authentication database (default: admin)
   --output-format    Report format: text or json (default: text)
   -h, --help         Show this help message

Any arguments after -- are forwarded to pt-mongodb-summary unchanged
(e.g. --no-version-check, --running-ops-samples, --sslCAFile).
EOS
    exit "${exit_code}"
}

if ! OPTS=$(getopt --options h --longoptions 'host:,port:,user:,password:,auth-database:,output-format:,help' -- "$@"); then
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
        --output-format)
            OUTPUT_FORMAT="$2"
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

if ! command -v pt-mongodb-summary > /dev/null 2>&1; then
    echo "pt-mongodb-summary not found. Install the percona-toolkit package on the target host." >&2
    exit 2
fi

case "$OUTPUT_FORMAT" in
    text | json) ;;
    *)
        echo "Error: --output-format must be 'text' or 'json'." >&2
        usage 1
        ;;
esac

# Known flags are assembled here; credentials use the --flag=value form so the
# password is never split off as a separate, more easily logged argument.
PMS_ARGS=(--output-format="$OUTPUT_FORMAT")
if [ -n "$USER" ]; then
    PMS_ARGS+=(--username="$USER" --authenticationDatabase="$AUTH_DB")
    if [ -n "$PASSWORD" ]; then
        PMS_ARGS+=(--password="$PASSWORD")
    fi
fi

echo "=== pt-mongodb-summary ==="
echo "Endpoint: $HOST:$PORT"
echo "Output format: $OUTPUT_FORMAT"
echo ""

# stdin is redirected from /dev/null so a missing credential cannot leave the
# tool waiting on an interactive prompt. The host:port positional goes last.
if pt-mongodb-summary "${PMS_ARGS[@]}" "$@" "${HOST}:${PORT}" < /dev/null; then
    echo ""
    echo "=== Done ==="
else
    echo "" >&2
    echo "pt-mongodb-summary exited with an error." >&2
    echo "Check the host/port and credentials, and that mongod is reachable." >&2
    exit 1
fi
