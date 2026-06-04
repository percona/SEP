#!/usr/bin/env bash

# ---
# title: "PostgreSQL Deadlocks Check"
# description: "This script checks for recent deadlock occurrences in PostgreSQL by searching logs."
# allow_extra_args: false
# sudo: optional
# service_type: postgresql
# parameters:
#  - name: dbname
#    type: str
#    label: Target database
#    description: Database to connect to (psql --dbname). Defaults to postgres.
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
LOG_GLOB=$($PSQL -tA -c "
    SELECT CASE
        WHEN current_setting('log_directory') LIKE '/%'
        THEN current_setting('log_directory') || '/*.log'
        ELSE current_setting('data_directory') || '/'
             || current_setting('log_directory') || '/*.log'
    END;
" 2> /dev/null) || LOG_GLOB=""

LOG_FILES=()
if [ -n "${LOG_GLOB}" ]; then
    shopt -s nullglob
    for path in ${LOG_GLOB}; do
        LOG_FILES+=("${path}")
    done
    shopt -u nullglob
fi

if [ ${#LOG_FILES[@]} -eq 0 ]; then
    echo "No deadlock entries found in PostgreSQL logs or problem occurred when querying for log_directory parameter."
else
    tail -50 "${LOG_FILES[@]}" 2> /dev/null | grep -i "deadlock" ||
        echo "No deadlock entries found in PostgreSQL logs or problem occurred when querying for log_directory parameter."
fi
