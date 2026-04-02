#!/usr/bin/env bash

# ---
# title: "PostgreSQL commit ratio check"
# description: "This script checks for databases with a low transaction commit ratio, indicating frequent rollbacks or aborted operations."
# allow_extra_args: false
# sudo: always
# service_type: postgresql
# alerts:
#   - PostgreSQLLowCommitRatio
# ---

# Usage: ./postgresql_commit_ratio.sh

set -euo pipefail

PSQL="psql"

$PSQL << SQL
SELECT datname, xact_commit, xact_rollback,
       ROUND((xact_rollback::numeric * 100) / NULLIF(xact_commit + xact_rollback, 0), 4) AS rollback_percent,
       ROUND((xact_commit::numeric * 100) / NULLIF(xact_commit + xact_rollback, 0), 4) AS commit_percent
FROM pg_stat_database
WHERE datname NOT IN ('template0', 'template1')
ORDER BY rollback_percent;
SQL

echo ""
echo "********* Rollback statements in pg_stat_activity *********"
echo ""
$PSQL << SQL
SELECT * FROM pg_stat_activity WHERE query ilike '%rollback%';
SQL

echo ""
echo "********* Long running transactions *********"
echo ""
$PSQL << SQL
SELECT now()-query_start age, *
FROM pg_stat_activity
WHERE now()-query_start > interval '7 minutes'
  AND query not ilike '%START_REPLICATION%';
SQL

echo ""
echo "********* Errors/rollbacks in PostgreSQL logs *********"
echo ""
grep -i "ERROR" /var/log/postgresql/postgresql-*.log* || true
grep -i "rollback" /var/log/postgresql/postgresql-*.log* || true
