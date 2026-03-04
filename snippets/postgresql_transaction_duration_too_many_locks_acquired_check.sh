#!/usr/bin/env bash

# ---
# title: "PostgreSQL Transaction Duration/Idle In Transaction/Too Many Locks Check"
# description: "This script identifies long-running active transactions and any blocking queries to diagnose transaction duration, idle-in-transaction, and too-many-locks-acquired alerts."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./postgresql_transaction_duration_too_many_locks_acquired_check.sh

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
echo "********* Idle in transaction sessions *********"
echo ""
$PSQL <<SQL
SELECT now()-query_start AS age, *
FROM pg_stat_activity
WHERE now()-query_start > interval '7 minutes'
  AND query NOT ILIKE '%START_REPLICATION%'
  AND state = 'idle in transaction'
SQL

echo ""
echo "********* Queries that are in the locked state *********"
echo ""
$PSQL <<SQL
SELECT a.datname,
       l.relation::regclass,
       l.transactionid,
       l.mode,
       l.GRANTED,
       a.usename,
       left(a.query, 50),
       a.query_start,
       age(now(), a.query_start) AS "age",
       a.pid
FROM pg_stat_activity a
JOIN pg_locks l ON l.pid = a.pid
WHERE mode ILIKE '%exclusive%';
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

echo ""
echo "********* Current idle_in_transaction_session_timeout setting *********"
echo ""
$PSQL <<SQL
SHOW idle_in_transaction_session_timeout;
SQL
