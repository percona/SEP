#!/usr/bin/env bash

# ---
# title: "PostgreSQL Transaction Wraparound Check"
# description: "This script checks database and table ages against autovacuum_freeze_max_age, ongoing vacuum progress, and oldest unfrozen tables."
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
#   - PostgreSQLWraparound
# ---

# Usage: ./postgresql_wraparound_check.sh

set -euo pipefail

DBNAME="${PGDATABASE:-postgres}"
if [[ ${1:-} == --dbname=* ]]; then
    DBNAME="${1#*=}"
elif [[ ${1:-} == --dbname ]]; then
    DBNAME="${2:-postgres}"
fi
export PGDATABASE="${DBNAME:-postgres}"

PSQL="psql"

echo "********* Database ages (oldest first) *********"
$PSQL << SQL
SELECT datname, age(datfrozenxid)
FROM pg_database
ORDER BY 2 DESC, 1 ASC;
SQL

echo ""
echo "********* autovacuum_freeze_max_age setting *********"
$PSQL << SQL
SHOW autovacuum_freeze_max_age;
SQL

echo ""
echo "********* Replication slot size *********"
$PSQL << SQL
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
echo "********* Ongoing vacuum progress *********"
$PSQL << SQL
SELECT p.pid, now() - a.xact_start AS duration,
       coalesce(wait_event_type ||'.'|| wait_event, 'f') AS waiting,
       CASE
           WHEN a.query ~*'^autovacuum.*to prevent wraparound' THEN 'wraparound'
           WHEN a.query ~*'^vacuum' THEN 'user'
           ELSE 'regular'
       END AS mode,
       p.datname AS database, p.relid::regclass AS table,
       p.phase,
       pg_size_pretty(p.heap_blks_total * current_setting('block_size')::int) AS table_size,
       pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
       pg_size_pretty(p.heap_blks_scanned * current_setting('block_size')::int) AS scanned,
       pg_size_pretty(p.heap_blks_vacuumed * current_setting('block_size')::int) AS vacuumed,
       COALESCE(round(100.0 * p.heap_blks_scanned / NULLIF(p.heap_blks_total, 0), 1), 0) AS scanned_pct,
       COALESCE(round(100.0 * p.heap_blks_vacuumed / NULLIF(p.heap_blks_total, 0), 1), 0) AS vacuumed_pct,
       p.index_vacuum_count,
       COALESCE(round(100.0 * p.num_dead_tuples / NULLIF(p.max_dead_tuples, 0), 1), 0) AS dead_pct
FROM pg_stat_progress_vacuum p
JOIN pg_stat_activity a USING (pid)
ORDER BY now() - a.xact_start DESC;
SQL

echo ""
echo "********* Top 10 oldest tables (candidates for vacuum freeze) *********"
$PSQL << SQL
WITH cur_vaccs AS (
    SELECT split_part(split_part(substring(query from 'public\..*'), '.', 2), ' ', 1) AS tab
    FROM pg_stat_activity
    WHERE query LIKE 'autovacuum%'
)
SELECT 'VACUUM FREEZE "' || n.nspname || '"."' || c.relname || '"; -- '
       || pg_size_pretty(pg_table_size(c.oid)) || ' -- age: ' || age(c.relfrozenxid) AS vacuum_command
FROM pg_class c
INNER JOIN pg_namespace n ON c.relnamespace = n.oid
LEFT JOIN pg_class t ON c.reltoastrelid = t.oid AND t.relkind = 't'
WHERE c.relkind IN ('r', 'm')
  AND NOT EXISTS (SELECT * FROM cur_vaccs WHERE tab = c.relname)
ORDER BY GREATEST(age(c.relfrozenxid), age(t.relfrozenxid)) DESC
LIMIT 10;
SQL
