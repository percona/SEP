#!/usr/bin/env bash

# ---
# title: "PostgreSQL Transaction Duration Check"
# description: "This script identifies long-running active transactions and any blocking queries to diagnose transaction duration alerts."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./postgresql_transaction_duration_check.sh

set -euo pipefail

PSQL="psql"

echo "********* Long-running active transactions *********"
echo ""
$PSQL <<SQL
SELECT now()-query_start AS age, *
FROM pg_stat_activity
WHERE now()-query_start > interval '7 minutes'
  AND query NOT ILIKE '%START_REPLICATION%'
  AND state = 'active'
SQL

echo ""
echo "********* Blocking queries *********"
echo ""
$PSQL <<SQL
SELECT activity.pid,
       activity.usename,
       activity.query,
       blocking.pid AS blocking_id,
       blocking.query AS blocking_query
FROM pg_stat_activity AS activity
JOIN pg_stat_activity AS blocking ON blocking.pid = ANY(pg_blocking_pids(activity.pid));
SQL

echo ""
echo "********* Current statement_timeout setting *********"
echo ""
$PSQL <<SQL
SHOW statement_timeout;
SQL
