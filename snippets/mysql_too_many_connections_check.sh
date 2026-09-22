#!/usr/bin/env bash

# ---
# title: "MySQL Too Many Connections Check"
# description: "This script checks MySQL connection usage, identifies connection sources, and detects lock contention causing connection pileup."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: MySQL defaults file
#    description: MySQL option file the client reads for connection settings.
# diagnostic_categories: []
# service_type: mysql
# alerts:
#   - MySQLTooManyConnections
# ---

# Usage: ./mysql_too_many_connections_check.sh [--defaults-file=path]

set -euo pipefail

DEFAULTS_FILE=""
if [[ ${1:-} == --defaults-file=* ]]; then
    DEFAULTS_FILE="$1"
    shift
elif [[ ${1:-} == --defaults-file ]]; then
    DEFAULTS_FILE="--defaults-file=${2}"
    shift 2
fi

MYSQL="mysql $DEFAULTS_FILE -B"

echo "********* Connection limits *********"
$MYSQL -e "SHOW GLOBAL VARIABLES LIKE 'max_connections';"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'Threads_connected';"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'Max_used_connections';"

echo ""
echo "********* Active (non-sleeping) processlist *********"
$MYSQL -e "SELECT * FROM information_schema.processlist WHERE command != 'Sleep' ORDER BY time DESC;"

echo ""
echo "********* Connection sources summary *********"
$MYSQL -e "SELECT user, host, db, command, COUNT(*) AS cnt FROM information_schema.processlist GROUP BY user, host, db, command ORDER BY cnt DESC;"

echo ""
echo "********* InnoDB status (transactions section) *********"
if ! innodb_status=$($MYSQL -e "SHOW ENGINE INNODB STATUS\G" 2>&1); then
    echo "Could not retrieve InnoDB status (check --defaults-file): $innodb_status"
else
    printf '%s\n' "$innodb_status" | head -100 || true
fi

echo ""
echo "********* Threads waiting for locks *********"
# Keep stderr out of the captured value: an empty result is what distinguishes
# "no threads are waiting" from "the query did not run", and a warning on an
# otherwise successful run would suppress that distinction.
LOCK_ERR=$(mktemp)
if ! lock_waiters=$($MYSQL -e "SELECT * FROM information_schema.processlist WHERE state LIKE '%lock%' ORDER BY time DESC;" 2> "$LOCK_ERR"); then
    echo "Could not query threads waiting for locks (check --defaults-file): $(cat "$LOCK_ERR")"
elif [ -z "$lock_waiters" ]; then
    echo "No threads waiting for locks."
else
    printf '%s\n' "$lock_waiters"
fi
rm -f "$LOCK_ERR"
