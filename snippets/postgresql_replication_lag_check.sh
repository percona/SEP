#!/usr/bin/env bash

# ---
# title: "PostgreSQL Replication Lag Check"
# description: "This script checks replication lag details including WAL positions, replication slots, blocking queries, and long-running transactions."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./postgresql_replication_lag_check.sh

set -euo pipefail

PSQL="psql"

echo "********* Replication status (pg_stat_replication) *********"
echo ""
$PSQL <<SQL
SELECT * FROM pg_stat_replication;
SQL

echo ""
echo "********* Replication lag with slots *********"
echo ""
$PSQL <<SQL
SELECT a.client_addr,
       b.slot_name,
       a.state,
       pg_current_wal_lsn() AS current_wal,
       a.replay_lsn,
       a.replay_lag AS lag_in_time,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), a.replay_lsn)) AS lag_in_size
FROM pg_stat_replication a
LEFT JOIN pg_replication_slots b ON a.pid = b.active_pid
ORDER BY pg_wal_lsn_diff(pg_current_wal_lsn(), a.replay_lsn) DESC;
SQL

echo ""
echo "********* Replication lag without slots *********"
echo ""
$PSQL <<SQL
SELECT application_name,
       state,
       pg_current_wal_lsn() AS current_wal,
       replay_lsn,
       replay_lag,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) AS size
FROM pg_stat_replication;
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
echo "********* Long-running transactions *********"
echo ""
$PSQL <<SQL
SELECT now()-query_start AS age, *
FROM pg_stat_activity
WHERE now()-query_start > interval '1 minute'
  AND state IN ('idle in transaction', 'active');
SQL
