#!/usr/bin/env bash

# ---
# title: "MySQL History Length Check"
# description: "This script checks InnoDB history list length and identifies long-running transactions that may block purge operations."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
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
$MYSQL -e "SHOW ENGINE INNODB STATUS\G" 2> /dev/null | grep -i "history list length" ||
    echo "Cannot retrieve InnoDB status."

echo ""
echo "********* Purge thread configuration *********"
$MYSQL -e "SHOW GLOBAL VARIABLES LIKE 'innodb_purge_threads';"

echo ""
echo "********* Long-running active queries *********"
$MYSQL -e "SELECT * FROM information_schema.processlist WHERE command != 'Sleep' ORDER BY time DESC LIMIT 20;"

echo ""
echo "********* Open transactions (including sleeping) *********"
$MYSQL -e "SELECT * FROM information_schema.innodb_trx ORDER BY trx_started;" 2> /dev/null ||
    echo "Cannot query innodb_trx."
