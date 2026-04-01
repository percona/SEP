#!/usr/bin/env bash

# ---
# title: "PostgreSQL max connections check"
# description: "This script checks the number of PostgreSQL connections against the max_connections limit to help troubleshoot connection exhaustion."
# allow_extra_args: false
# sudo: optional
# service_type: postgresql
# alerts:
#   - PostgreSQLMaxConnections
# ---

# Usage: ./postgresql_max_connections_check.sh

set -euo pipefail

PSQL="psql"

# May need to handle connecting on the server as postgres superuser here, given that this
# is likely to run when connections are exhausted.
echo "********* Connection usage summary *********"
echo ""
$PSQL << SQL
SHOW max_connections;
SELECT count(*) AS total_connections FROM pg_stat_activity;
SQL

echo ""
echo "********* Connections by application/user *********"
echo ""
$PSQL << SQL
SELECT usename, application_name, client_addr, count(*)
FROM pg_stat_activity
GROUP BY usename, application_name, client_addr
ORDER BY 4 DESC;
SQL

echo ""
echo "********* Idle/idle-in-transaction connections *********"
echo ""
$PSQL << SQL
SELECT pid, usename, state, query
FROM pg_stat_activity
WHERE state IN ('idle', 'idle in transaction')
ORDER BY state, pid;
SQL
