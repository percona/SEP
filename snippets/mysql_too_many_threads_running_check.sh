#!/usr/bin/env bash

# ---
# title: "MySQL Too Many Threads Running Check"
# description: "This script checks running thread count, active processlist, and InnoDB status to diagnose high thread concurrency."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# service_type: mysql
# alerts:
#   - MySQLTooManyThreadsRunning
# ---

# Usage: ./mysql_too_many_threads_running_check.sh [--defaults-file=path]

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

echo "********* Thread status *********"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'Threads_%';"

echo ""
echo "********* Active (non-sleeping) processlist *********"
$MYSQL -e "SELECT * FROM information_schema.processlist WHERE command != 'Sleep' ORDER BY time DESC;"

echo ""
echo "********* InnoDB status *********"
if ! $MYSQL -e "SHOW ENGINE INNODB STATUS\G" 2> /dev/null | head -150; then
    status=${PIPESTATUS[0]}
    if [[ $status -ne 0 && $status -ne 141 ]]; then
        echo "Cannot retrieve InnoDB status."
    fi
fi

echo ""
echo "********* System load *********"
uptime
