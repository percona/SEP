#!/usr/bin/env bash

# ---
# title: "PostgreSQL max connections check"
# description: "This script checks the number of PostgreSQL connections against the max_connections limit to help troubleshoot connection exhaustion."
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
#   - PostgreSQLMaxConnections
# ---

# Usage: ./postgresql_max_connections_check.sh

set -euo pipefail

DBNAME="${PGDATABASE:-postgres}"
if [[ ${1:-} == --dbname=* ]]; then
    DBNAME="${1#*=}"
elif [[ ${1:-} == --dbname ]]; then
    DBNAME="${2:-postgres}"
fi
export PGDATABASE="${DBNAME:-postgres}"

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
