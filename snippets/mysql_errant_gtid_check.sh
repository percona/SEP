#!/usr/bin/env bash

# ---
# title: "MySQL Errant GTID Check"
# description: "This script checks for errant GTIDs on replica nodes by comparing executed GTID sets between replica and source."
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
#   - MySQLErrantGTID
# ---

# Usage: ./mysql_errant_gtid_check.sh [--defaults-file=path]

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

echo "********* GTID mode *********"
if ! gtid_mode=$($MYSQL -e "SELECT @@gtid_mode;" 2>&1); then
    echo "Could not read GTID mode (check --defaults-file): $gtid_mode"
else
    printf '%s\n' "$gtid_mode"
fi

echo ""
echo "********* Server UUID *********"
$MYSQL -e "SELECT @@server_uuid;"

echo ""
echo "********* Executed GTID set *********"
$MYSQL -e "SELECT @@global.gtid_executed\G"

echo ""
echo "********* Replica status (GTID details) *********"
if $MYSQL -e 'SHOW REPLICA STATUS\G' 2>&1 | grep -q "You have an error"; then
    REPLICA_STATUS_QUERY='SHOW SLAVE STATUS\G'
else
    REPLICA_STATUS_QUERY='SHOW REPLICA STATUS\G'
fi

if ! replica_status=$($MYSQL -e "$REPLICA_STATUS_QUERY" 2>&1); then
    echo "Could not read replica status (check --defaults-file): $replica_status"
elif ! printf '%s\n' "$replica_status" | grep -E "Gtid|gtid|Source_UUID|Master_UUID|Executed|Retrieved"; then
    echo "Replica status reported no GTID fields."
fi

echo ""
echo "********* Read-only status *********"
$MYSQL -e "SELECT @@global.read_only AS read_only, @@global.super_read_only AS super_read_only;"
