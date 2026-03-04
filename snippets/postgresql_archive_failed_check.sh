#!/usr/bin/env bash

# ---
# title: "PostgreSQL Archive Failed Check"
# description: "This script checks WAL archiving configuration, archiver status, and logs to diagnose archive failures."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./postgresql_archive_failed_check.sh

set -euo pipefail

PSQL="psql"

echo "********* Archive configuration *********"
echo ""
$PSQL <<SQL
SELECT name, setting
FROM pg_settings
WHERE name IN ('archive_mode', 'archive_command', 'archive_timeout');
SQL

echo ""
echo "********* Archiver status *********"
echo ""
$PSQL <<SQL
SELECT * FROM pg_stat_archiver;
SQL

echo ""
echo "********* pg_wal directory size *********"
echo ""
$PSQL -t -A <<SQL
SELECT setting FROM pg_settings WHERE name = 'data_directory';
SQL
PGDATA=$($PSQL -t -A -c "SELECT setting FROM pg_settings WHERE name = 'data_directory'" 2> /dev/null) || true
if [ -n "${PGDATA:-}" ] && [ -d "$PGDATA/pg_wal" ]; then
    du -sh "$PGDATA/pg_wal" 2>/dev/null || echo "Cannot access pg_wal directory (may need elevated privileges)."
    echo ""
    ls -la "$PGDATA/pg_wal/" 2>/dev/null | tail -20 || true
else
    echo "Could not determine pg_wal location."
fi
