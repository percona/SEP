#!/usr/bin/env bash

# ---
# title: "PostgreSQL Archive Failed Check"
# description: "This script checks WAL archiving configuration, archiver status, and logs to diagnose archive failures."
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
#   - PostgreSQLArchiveFailed
# ---

# Usage: ./postgresql_archive_failed_check.sh

set -euo pipefail

DBNAME="${PGDATABASE:-postgres}"
if [[ ${1:-} == --dbname=* ]]; then
    DBNAME="${1#*=}"
elif [[ ${1:-} == --dbname ]]; then
    DBNAME="${2:-postgres}"
fi
export PGDATABASE="${DBNAME:-postgres}"

PSQL="psql"

echo "********* Archive configuration *********"
echo ""
$PSQL << SQL
SELECT name, setting
FROM pg_settings
WHERE name IN ('archive_mode', 'archive_command', 'archive_timeout');
SQL

echo ""
echo "********* Archiver status *********"
echo ""
$PSQL << SQL
SELECT * FROM pg_stat_archiver;
SQL

echo ""
echo "********* pg_wal directory size *********"
echo ""
PGDATA=$($PSQL -t -A -c "SELECT setting FROM pg_settings WHERE name = 'data_directory'" 2> /dev/null) || true
echo "Data directory: ${PGDATA:-unknown}"
if [ -n "${PGDATA:-}" ] && test -d "$PGDATA/pg_wal"; then
    du -sh "$PGDATA/pg_wal" 2> /dev/null || echo "Cannot access pg_wal directory (may need elevated privileges)."
    echo ""
    find "$PGDATA/pg_wal/" -maxdepth 1 -printf "%M %u %g %10s %TY-%Tm-%Td %TH:%TM %f\n" 2> /dev/null | tail -20 || true
elif [ -n "${PGDATA:-}" ] && test -e "$PGDATA/pg_wal"; then
    echo "pg_wal exists but is not accessible (may need elevated privileges)."
else
    echo "Could not determine or access pg_wal location (may need elevated privileges)."
fi

echo ""
echo "********* Recent archiver failures in PostgreSQL logs *********"
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
    echo "No archiver errors found in PostgreSQL logs or problem occurred when querying for log_directory parameter."
else
    tail -200 "${LOG_FILES[@]}" 2> /dev/null | grep -iE "archiver|archive command failed|could not archive" ||
        echo "No archiver errors found in PostgreSQL logs or problem occurred when querying for log_directory parameter."
fi
