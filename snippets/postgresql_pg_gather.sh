#!/usr/bin/env bash

# ---
# title: PostgreSQL pg_gather Data Collection
# description: Downloads and runs the Percona pg_gather script (gather.sql) against a target database and returns the output to stdout or a file. Optionally masquerades IP addresses and email-like values for PII-sensitive sharing.
# allow_extra_args: false
# sudo: optional
# service_type: postgresql
# parameters:
#  - name: dbname
#    type: str
#    label: Database name
#    description: PostgreSQL database to connect to (passed as psql -d).
#    required: true
#  - name: host
#    type: str
#    label: Host
#    description: PostgreSQL host (psql -h). Omit to use libpq defaults.
#    placeholder: 127.0.0.1
#  - name: port
#    type: int
#    label: Port
#    description: PostgreSQL port (psql -p). Omit to use libpq defaults.
#    placeholder: 5432
#  - name: user
#    type: str
#    label: User
#    description: PostgreSQL user (psql -U). pg_gather recommends a superuser, rds_superuser, or an account with pg_monitor.
#    placeholder: postgres
#  - name: output
#    type: str
#    label: Output destination
#    description: Where to send the gather.sql output.
#    default: file
#    choices:
#      - value: stdout
#        label: Print to the terminal
#      - value: file
#        label: Write the output to a file named by the timestamp (default)
#  - name: output-file
#    type: str
#    label: Output file path
#    description: Override path when --output=file. Defaults to pg_gather_<epoch>.out in the current directory.
#    placeholder: /tmp/pg_gather.out
#  - name: script
#    type: str
#    label: gather.sql override path
#    description: Use a local copy of gather.sql instead of downloading the latest version. Useful in air-gapped environments.
#    placeholder: /tmp/gather.sql
#  - name: mask
#    type: bool
#    label: Masquerade PII
#    description: Redact IPv4 / IPv6 addresses and email-like values in the captured output before writing it.
#    default: false
# atw:
#  - OVERALL_SLOWNESS
#  - NOT_RESPONDING
#  - WRITES_ARE_BLOCKED
#  - PERFORMANCE_OTHER
#  - TEMPORARY_STALLS
# ---

set -euo pipefail

GATHER_URL="https://raw.githubusercontent.com/percona/support-snippets/master/postgresql/pg_gather/gather.sql"

DBNAME_ARG=""
HOST_ARG=""
PORT_ARG=""
USER_ARG=""
OUTPUT_MODE="file"
OUTPUT_FILE_ARG=""
SCRIPT_ARG=""
MASK=0

usage() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: $(basename "$0") --dbname <name> [OPTIONS]

Run Percona pg_gather (gather.sql) against a PostgreSQL database.

Options:
  --dbname <name>           Database to connect to (required).
  --host <host>             PostgreSQL host (psql -h).
  --port <port>             PostgreSQL port (psql -p).
  --user <user>             PostgreSQL user (psql -U).
  --output <stdout|file>    Where to send gather output (default: file).
  --output-file <path>      Explicit output file path (default: pg_gather_<epoch>.out).
  --script <path>           Use a local gather.sql instead of downloading.
  --mask                    Redact IPv4/IPv6 and email-like values in the output.
  -h, --help                Show this help message.

Notes:
  * libpq env vars (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGPASSFILE) and ~/.pgpass
    are honoured for any connection parameter not set explicitly.
  * pg_gather recommends running as a superuser, rds_superuser, or an account
    with the pg_monitor role.
EOS
    exit "${exit_code}"
}

if ! OPTS=$(getopt --options h --longoptions 'dbname:,host:,port:,user:,output:,output-file:,script:,mask,help' -- "$@"); then
    echo "Error parsing options" >&2
    usage 1
fi

eval set -- "$OPTS"

while [[ -n $* ]]; do
    case "$1" in
        --dbname)
            DBNAME_ARG="$2"
            shift 2
            ;;
        --host)
            HOST_ARG="$2"
            shift 2
            ;;
        --port)
            PORT_ARG="$2"
            shift 2
            ;;
        --user)
            USER_ARG="$2"
            shift 2
            ;;
        --output)
            OUTPUT_MODE="$2"
            shift 2
            ;;
        --output-file)
            OUTPUT_FILE_ARG="$2"
            shift 2
            ;;
        --script)
            SCRIPT_ARG="$2"
            shift 2
            ;;
        --mask)
            MASK=1
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

if [[ -z $DBNAME_ARG ]]; then
    echo "Error: --dbname is required." >&2
    usage 1
fi

case "$OUTPUT_MODE" in
    stdout | file) ;;
    *)
        echo "Error: --output must be 'stdout' or 'file'." >&2
        usage 1
        ;;
esac

if ! command -v psql > /dev/null 2>&1; then
    echo "Error: psql is not available on PATH." >&2
    exit 1
fi

# Stage gather.sql so the user-supplied --script path stays untouched and the
# downloaded copy is cleaned up on exit.
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

GATHER_SCRIPT="$WORKDIR/gather.sql"
if [[ -n $SCRIPT_ARG ]]; then
    if [[ ! -r $SCRIPT_ARG ]]; then
        echo "Error: --script path '$SCRIPT_ARG' is not readable." >&2
        exit 1
    fi
    cp "$SCRIPT_ARG" "$GATHER_SCRIPT"
    echo "Using local gather.sql: $SCRIPT_ARG" >&2
else
    echo "Downloading gather.sql from $GATHER_URL ..." >&2
    if command -v curl > /dev/null 2>&1; then
        if ! curl -fsSL "$GATHER_URL" -o "$GATHER_SCRIPT"; then
            echo "Error: failed to download gather.sql via curl." >&2
            exit 1
        fi
    elif command -v wget > /dev/null 2>&1; then
        if ! wget -q "$GATHER_URL" -O "$GATHER_SCRIPT"; then
            echo "Error: failed to download gather.sql via wget." >&2
            exit 1
        fi
    else
        echo "Error: neither curl nor wget is available; pass --script <path>." >&2
        exit 1
    fi
fi

if [[ ! -s $GATHER_SCRIPT ]]; then
    echo "Error: gather.sql is empty." >&2
    exit 1
fi

PSQL_ARGS=(-X -d "$DBNAME_ARG" -f "$GATHER_SCRIPT")
[[ -n $HOST_ARG ]] && PSQL_ARGS=(-h "$HOST_ARG" "${PSQL_ARGS[@]}")
[[ -n $PORT_ARG ]] && PSQL_ARGS=(-p "$PORT_ARG" "${PSQL_ARGS[@]}")
[[ -n $USER_ARG ]] && PSQL_ARGS=(-U "$USER_ARG" "${PSQL_ARGS[@]}")

RAW_OUTPUT="$WORKDIR/pg_gather.raw"

echo "Running pg_gather against database '$DBNAME_ARG' ..." >&2
if ! psql "${PSQL_ARGS[@]}" > "$RAW_OUTPUT" 2> "$WORKDIR/psql.err"; then
    echo "Error: psql failed to execute gather.sql." >&2
    if [[ -s "$WORKDIR/psql.err" ]]; then
        echo "--- psql stderr ---" >&2
        cat "$WORKDIR/psql.err" >&2
    fi
    exit 1
fi
# Keep warnings visible to the operator without polluting the captured output.
if [[ -s "$WORKDIR/psql.err" ]]; then
    cat "$WORKDIR/psql.err" >&2
fi

# Masquerade IPv4 / IPv6 / email-like values in-place. This pass runs on the
# raw psql output (a flat text file), so column alignment may shift slightly
# when placeholder strings differ in length from the originals. Anything more
# aggressive risks mangling pg_gather's tabular sections.
#
# IPv6 patterns:
#   - Compressed form (contains "::"): matches "::1", "fe80::1", "2001:db8::1".
#     The "::" anchor avoids false positives on time strings like 10:30:45 that
#     use single colons only.
#   - Full 8-group form: 7 hex-colon groups followed by a final hex group.
mask_output() {
    local src="$1" dst="$2"
    sed -E \
        -e 's/([0-9]{1,3}\.){3}[0-9]{1,3}/<ipv4-redacted>/g' \
        -e 's/[0-9a-fA-F]*(:[0-9a-fA-F]+)*::([0-9a-fA-F]+:?)*[0-9a-fA-F]*/<ipv6-redacted>/g' \
        -e 's/([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}/<ipv6-redacted>/g' \
        -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/<email-redacted>/g' \
        "$src" > "$dst"
}

FINAL_OUTPUT="$RAW_OUTPUT"
if [[ $MASK -eq 1 ]]; then
    FINAL_OUTPUT="$WORKDIR/pg_gather.masked"
    mask_output "$RAW_OUTPUT" "$FINAL_OUTPUT"
fi

if [[ $OUTPUT_MODE == "stdout" ]]; then
    cat "$FINAL_OUTPUT"
else
    if [[ -z $OUTPUT_FILE_ARG ]]; then
        OUTPUT_FILE_ARG="pg_gather_$(date +%s).out"
    fi
    cp "$FINAL_OUTPUT" "$OUTPUT_FILE_ARG"
    echo "Output written to: $OUTPUT_FILE_ARG" >&2
    if [[ $MASK -eq 1 ]]; then
        echo "Masking: ON (IPv4/IPv6/email patterns redacted)" >&2
    fi
fi
