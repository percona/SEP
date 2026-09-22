#!/usr/bin/env bash

# ---
# title: "MySQL History Length Check"
# description: "This script checks InnoDB history list length and identifies long-running transactions that may block purge operations."
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
#   - MySQLHistoryListLengthHigh
# ---

# Usage: ./mysql_history_length_check.sh [--defaults-file=path]

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

echo "********* InnoDB History List Length *********"
if ! innodb_status=$($MYSQL -e "SHOW ENGINE INNODB STATUS\G" 2>&1); then
    echo "Could not retrieve InnoDB status (check --defaults-file): $innodb_status"
elif ! printf '%s\n' "$innodb_status" | grep -i "history list length"; then
    echo "InnoDB status reported no history list length."
fi

echo ""
echo "********* Purge thread configuration *********"
$MYSQL -e "SHOW GLOBAL VARIABLES LIKE 'innodb_purge_threads';"

echo ""
echo "********* Long-running active queries *********"
$MYSQL -e "SELECT * FROM information_schema.processlist WHERE command != 'Sleep' ORDER BY time DESC LIMIT 20;"

echo ""
echo "********* Open transactions (including sleeping) *********"
if ! innodb_trx=$($MYSQL -e "SELECT * FROM information_schema.innodb_trx ORDER BY trx_started;" 2>&1); then
    echo "Could not query innodb_trx (check --defaults-file): $innodb_trx"
else
    printf '%s\n' "$innodb_trx"
fi
