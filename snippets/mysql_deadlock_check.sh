#!/usr/bin/env bash

# ---
# title: "MySQL Deadlock Check"
# description: "This script checks for the most recent InnoDB deadlock and current lock waits to diagnose deadlock alerts."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# service_type: mysql
# alerts:
#   - MySQLDeadlock
#   - MySQLHistoryListLengthHigh
# ---

# Usage: ./mysql_deadlock_check.sh [--defaults-file=path]

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

echo "********* InnoDB status (LATEST DETECTED DEADLOCK section) *********"
$MYSQL -e "SHOW ENGINE INNODB STATUS\G" 2> /dev/null || echo "Cannot retrieve InnoDB status."
