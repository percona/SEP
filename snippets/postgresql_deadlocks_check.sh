#!/usr/bin/env bash

# ---
# title: "PostgreSQL Deadlocks Check"
# description: "This script checks for recent deadlock occurrences in PostgreSQL by searching logs."
# allow_extra_args: false
# sudo: optional
# diagnostic_categories: []
# service_type: postgresql
# parameters:
#  - name: dbname
#    type: str
#    label: Target database
#    description: The PostgreSQL database this script connects to.
#    default: postgres
# alerts:
#   - PostgreSQLDeadlocks
# ---

# Usage: ./postgresql_deadlocks_check.sh

set -euo pipefail

DBNAME="${PGDATABASE:-postgres}"
if [[ ${1:-} == --dbname=* ]]; then
    DBNAME="${1#*=}"
elif [[ ${1:-} == --dbname ]]; then
    DBNAME="${2:-postgres}"
fi
export PGDATABASE="${DBNAME:-postgres}"

PSQL="psql"

echo "********* Recent deadlock entries in PostgreSQL logs *********"
echo ""
# Keep stderr out of the captured value: it is expanded as a glob, and psql
# writes warnings there on runs that otherwise succeed.
PSQL_ERR=$(mktemp)
if ! LOG_GLOB=$($PSQL -tA -c "
    SELECT CASE
        WHEN current_setting('log_directory') LIKE '/%'
        THEN current_setting('log_directory') || '/*.log'
        ELSE current_setting('data_directory') || '/'
             || current_setting('log_directory') || '/*.log'
    END;
" 2> "$PSQL_ERR"); then
    echo "Could not read log_directory from PostgreSQL (check --dbname): $(cat "$PSQL_ERR")"
    LOG_GLOB=""
    LOG_DIR_KNOWN=0
else
    LOG_DIR_KNOWN=1
fi
rm -f "$PSQL_ERR"

LOG_FILES=()
if [ -n "${LOG_GLOB}" ]; then
    shopt -s nullglob
    for path in ${LOG_GLOB}; do
        LOG_FILES+=("${path}")
    done
    shopt -u nullglob
fi

if [ "$LOG_DIR_KNOWN" -eq 0 ]; then
    echo "Log files were not searched, because log_directory could not be read."
elif [ ${#LOG_FILES[@]} -eq 0 ]; then
    echo "No PostgreSQL log files found under log_directory."
elif ! log_tail=$(tail -50 "${LOG_FILES[@]}" 2>&1); then
    echo "Could not read the PostgreSQL log files: $log_tail"
elif ! printf '%s\n' "$log_tail" | grep -i "deadlock"; then
    echo "No deadlock entries found in PostgreSQL logs."
fi
