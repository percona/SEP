#!/usr/bin/env bash

# ---
# title: "MySQL Errant GTID Check"
# description: "This script checks for errant GTIDs on replica nodes by comparing executed GTID sets between replica and source."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# ---

# Usage: ./mysql_errant_gtid_check.sh [--defaults-file=path]

set -euo pipefail

DEFAULTS_FILE=""
if [[ "${1:-}" == --defaults-file=* ]]; then
    DEFAULTS_FILE="$1"
    shift
elif [[ "${1:-}" == --defaults-file ]]; then
    DEFAULTS_FILE="--defaults-file=${2}"
    shift 2
fi

MYSQL="mysql $DEFAULTS_FILE -B"

echo "********* GTID mode *********"
echo ""
$MYSQL -e "SELECT @@gtid_mode;" 2> /dev/null || echo "GTID mode not available."

echo ""
echo "********* Server UUID *********"
echo ""
$MYSQL -e "SELECT @@server_uuid;"

echo ""
echo "********* Executed GTID set *********"
echo ""
$MYSQL -e "SELECT @@global.gtid_executed\G"

echo ""
echo "********* Replica status (GTID details) *********"
echo ""
if ! $MYSQL -e 'SHOW REPLICA STATUS\G' 2>&1 | grep -q "You have an error"; then
    $MYSQL -e 'SHOW REPLICA STATUS\G' 2> /dev/null | grep -E "Gtid|gtid|Source_UUID|Master_UUID|Executed|Retrieved" || true
else
    $MYSQL -e 'SHOW SLAVE STATUS\G' 2> /dev/null | grep -E "Gtid|gtid|Source_UUID|Master_UUID|Executed|Retrieved" || true
fi

echo ""
echo "********* Read-only status *********"
echo ""
$MYSQL -e "SELECT @@global.read_only AS read_only, @@global.super_read_only AS super_read_only;"
