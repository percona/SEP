#!/usr/bin/env bash

# ---
# title: PostgreSQL Query Tuning (EXPLAIN ANALYZE)
# description: Wraps a user-supplied query in BEGIN/EXPLAIN (ANALYZE, ...)/ROLLBACK and runs it via psql -X -f. Selects EXPLAIN modifiers based on the detected PostgreSQL version (BUFFERS/SETTINGS/WAL/MEMORY/SERIALIZE). Writes the formatted explain output to a file for sharing with Percona support, with optional PII masking.
# allow_extra_args: false
# sudo: optional
# service_type: postgresql
# parameters:
#  - name: dbname
#    type: str
#    label: Database name
#    description: PostgreSQL database to connect to (psql -d).
#    required: true
#  - name: query
#    type: str
#    label: SQL statement
#    description: The SQL statement to analyze. Mutually exclusive with --query-file. A trailing semicolon is stripped if present.
#    placeholder: SELECT * FROM orders WHERE customer_id = 42
#  - name: query-file
#    type: str
#    label: SQL statement file
#    description: Path to a file containing the SQL statement to analyze. Mutually exclusive with --query.
#    placeholder: /tmp/query.sql
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
#    description: PostgreSQL user (psql -U). Omit to use libpq defaults.
#    placeholder: postgres
#  - name: output-file
#    type: str
#    label: Output file path
#    description: Destination for the explain output. Defaults to explain_<epoch>.out in the current directory.
#    placeholder: /tmp/explain.out
#  - name: explain-options
#    type: str
#    label: EXPLAIN options override
#    description: Override the auto-selected EXPLAIN options. Provide the contents of the parentheses, e.g. "ANALYZE, COSTS, VERBOSE, BUFFERS".
#    placeholder: ANALYZE, COSTS, VERBOSE, BUFFERS, SETTINGS, WAL
#  - name: mask
#    type: bool
#    label: Masquerade PII
#    description: Redact IPv4 / IPv6 / email-like values in the captured explain output. Indentation is preserved so plan alignment stays usable.
#    default: false
# atw:
#  - QUERY_TUNING_OPTIMIZATION
# ---

set -euo pipefail

DBNAME_ARG=""
QUERY_ARG=""
QUERY_FILE_ARG=""
HOST_ARG=""
PORT_ARG=""
USER_ARG=""
OUTPUT_FILE_ARG=""
EXPLAIN_OPTS_ARG=""
MASK=0

usage() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: $(basename "$0") --dbname <name> (--query <sql> | --query-file <path>) [OPTIONS]

Run EXPLAIN (ANALYZE, ...) on a query and capture the plan into a file for
sharing with Percona support. The statement is wrapped in BEGIN; ... ROLLBACK;
so DML side effects are discarded.

Options:
  --dbname <name>            Database to connect to (required).
  --query <sql>              Inline SQL statement to analyze.
  --query-file <path>        SQL statement file (alternative to --query).
  --host <host>              PostgreSQL host (psql -h).
  --port <port>              PostgreSQL port (psql -p).
  --user <user>              PostgreSQL user (psql -U).
  --output-file <path>       Destination file (default: explain_<epoch>.out).
  --explain-options <opts>   Override the EXPLAIN modifier list (between the
                             parentheses). Skips version auto-detection.
  --mask                     Redact IPv4 / IPv6 / email-like values in output.
  -h, --help                 Show this help message.

Default EXPLAIN modifiers per detected server version:
  <  PG 12  : ANALYZE, COSTS, VERBOSE, BUFFERS
  PG 12     : ANALYZE, COSTS, VERBOSE, BUFFERS, SETTINGS
  PG 13-16  : ANALYZE, COSTS, VERBOSE, BUFFERS, SETTINGS, WAL
  PG 17+    : ANALYZE, COSTS, VERBOSE, BUFFERS, SETTINGS, WAL, MEMORY, SERIALIZE
EOS
    exit "${exit_code}"
}

if ! OPTS=$(getopt --options h --longoptions 'dbname:,query:,query-file:,host:,port:,user:,output-file:,explain-options:,mask,help' -- "$@"); then
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
        --query)
            QUERY_ARG="$2"
            shift 2
            ;;
        --query-file)
            QUERY_FILE_ARG="$2"
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
        --output-file)
            OUTPUT_FILE_ARG="$2"
            shift 2
            ;;
        --explain-options)
            EXPLAIN_OPTS_ARG="$2"
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

if [[ -n $QUERY_ARG && -n $QUERY_FILE_ARG ]]; then
    echo "Error: --query and --query-file are mutually exclusive." >&2
    usage 1
fi

if [[ -z $QUERY_ARG && -z $QUERY_FILE_ARG ]]; then
    echo "Error: provide --query or --query-file." >&2
    usage 1
fi

if [[ -n $QUERY_FILE_ARG ]]; then
    if [[ ! -r $QUERY_FILE_ARG ]]; then
        echo "Error: --query-file '$QUERY_FILE_ARG' is not readable." >&2
        exit 1
    fi
    QUERY_TEXT=$(cat "$QUERY_FILE_ARG")
else
    QUERY_TEXT="$QUERY_ARG"
fi

# Normalize the query so it stays a single statement when embedded into analyze.sql.
# This avoids accidentally creating additional psql/script lines when the input
# contains newlines.
QUERY_TEXT=${QUERY_TEXT//$'\r'/ }
QUERY_TEXT=${QUERY_TEXT//$'\n'/ }

# Trim trailing whitespace / semicolons; we add the `;` after the EXPLAIN block
# so the user's query slots in cleanly regardless of how they terminated it.
while [[ $QUERY_TEXT == *[[:space:]] || $QUERY_TEXT == *';' ]]; do
    QUERY_TEXT="${QUERY_TEXT%[[:space:]]}"
    QUERY_TEXT="${QUERY_TEXT%;}"
done

# Require a single statement to keep BEGIN/ROLLBACK safety guarantees.
if [[ $QUERY_TEXT == *';'* ]]; then
    echo "Error: query must be a single statement (embedded ';' is not allowed)." >&2
    exit 1
fi

if [[ -z $QUERY_TEXT ]]; then
    echo "Error: query is empty after trimming." >&2
    exit 1
fi

if ! command -v psql > /dev/null 2>&1; then
    echo "Error: psql is not available on PATH." >&2
    exit 1
fi

# Build a reusable psql connection prefix. Connection flags must come BEFORE
# any -c / -f / -d. We keep DB name separate so the helper detect_version()
# can reuse the prefix verbatim.
PSQL_CONN=()
[[ -n $HOST_ARG ]] && PSQL_CONN+=(-h "$HOST_ARG")
[[ -n $PORT_ARG ]] && PSQL_CONN+=(-p "$PORT_ARG")
[[ -n $USER_ARG ]] && PSQL_CONN+=(-U "$USER_ARG")

if [[ -z $EXPLAIN_OPTS_ARG ]]; then
    echo "Detecting PostgreSQL server version ..." >&2
    if ! VER_NUM=$(psql "${PSQL_CONN[@]}" -d "$DBNAME_ARG" -tA -X -c "SHOW server_version_num;" 2> /dev/null); then
        echo "Error: could not connect to '$DBNAME_ARG' to detect server version. Pass --explain-options to skip detection." >&2
        exit 1
    fi
    VER_NUM=$(echo "$VER_NUM" | tr -d '[:space:]')
    if ! [[ $VER_NUM =~ ^[0-9]+$ ]]; then
        echo "Error: unexpected server_version_num value: '$VER_NUM'." >&2
        exit 1
    fi
    if ((VER_NUM >= 170000)); then
        EXPLAIN_OPTS="ANALYZE, COSTS, VERBOSE, BUFFERS, SETTINGS, WAL, MEMORY, SERIALIZE"
    elif ((VER_NUM >= 130000)); then
        EXPLAIN_OPTS="ANALYZE, COSTS, VERBOSE, BUFFERS, SETTINGS, WAL"
    elif ((VER_NUM >= 120000)); then
        EXPLAIN_OPTS="ANALYZE, COSTS, VERBOSE, BUFFERS, SETTINGS"
    else
        EXPLAIN_OPTS="ANALYZE, COSTS, VERBOSE, BUFFERS"
    fi
    echo "Detected server_version_num=$VER_NUM -> EXPLAIN ($EXPLAIN_OPTS)" >&2
else
    EXPLAIN_OPTS="$EXPLAIN_OPTS_ARG"
    echo "Using EXPLAIN options override: ($EXPLAIN_OPTS)" >&2
fi

# Stage analyze.sql in a temp dir; we feed it to psql with -X -f so the
# alignment of the explain output is preserved (per the data-collection guide,
# "please avoid copy-pasting the content").
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

ANALYZE_SQL="$WORKDIR/analyze.sql"
cat > "$ANALYZE_SQL" << EOF
\set ON_ERROR_STOP on
\pset pager off
\x off
BEGIN;
EXPLAIN (${EXPLAIN_OPTS}) ${QUERY_TEXT};
ROLLBACK;
EOF

if [[ -z $OUTPUT_FILE_ARG ]]; then
    OUTPUT_FILE_ARG="explain_$(date +%s).out"
fi

RAW_OUTPUT="$WORKDIR/explain.raw"

echo "Running EXPLAIN ANALYZE against database '$DBNAME_ARG' ..." >&2
if ! psql "${PSQL_CONN[@]}" -d "$DBNAME_ARG" -X -f "$ANALYZE_SQL" > "$RAW_OUTPUT" 2> "$WORKDIR/psql.err"; then
    echo "Error: psql failed running analyze.sql." >&2
    if [[ -s "$WORKDIR/psql.err" ]]; then
        echo "--- psql stderr ---" >&2
        cat "$WORKDIR/psql.err" >&2
    fi
    echo "--- analyze.sql (for reference) ---" >&2
    cat "$ANALYZE_SQL" >&2
    exit 1
fi
if [[ -s "$WORKDIR/psql.err" ]]; then
    cat "$WORKDIR/psql.err" >&2
fi

# PII masking pass. Three substitutions:
#   - IPv4: safe everywhere; EXPLAIN cost notation like "cost=0.29..8.31" does
#     not match because IPv4 requires exactly three dots between four numbers.
#   - IPv6: limited to values inside single quotes (i.e. inet literals like
#     '::1'::inet, 'fe80::1', 'a:b:c:d:e:f:g:h'). A broad IPv6 regex would
#     also match PostgreSQL cast operators like ::text / ::bytea / ::inet and
#     corrupt the EXPLAIN plan — which the PDF explicitly warns against.
#   - Email: low false-positive risk in EXPLAIN output.
# Plan column alignment may shift slightly because placeholder strings differ
# in length from the originals, but the structural indentation that matters
# for reading EXPLAIN output (the leading "->" arrows and per-node padding)
# is preserved.
mask_output() {
    local src="$1" dst="$2"
    sed -E \
        -e 's/([0-9]{1,3}\.){3}[0-9]{1,3}/<ipv4-redacted>/g' \
        -e "s/'[0-9a-fA-F]{0,4}(:[0-9a-fA-F]{0,4}){2,7}'/'<ipv6-redacted>'/g" \
        -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/<email-redacted>/g' \
        "$src" > "$dst"
}

if [[ $MASK -eq 1 ]]; then
    mask_output "$RAW_OUTPUT" "$OUTPUT_FILE_ARG"
else
    cp "$RAW_OUTPUT" "$OUTPUT_FILE_ARG"
fi

echo "Output written to: $OUTPUT_FILE_ARG" >&2
echo "EXPLAIN options:   ($EXPLAIN_OPTS)" >&2
if [[ $MASK -eq 1 ]]; then
    echo "Masking:           ON (IPv4/IPv6/email patterns redacted)" >&2
fi
