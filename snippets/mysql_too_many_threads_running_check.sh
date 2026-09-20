#!/usr/bin/env bash

# ---
# title: "MySQL Too Many Threads Running Check"
# description: "This script checks running thread count, active processlist, and InnoDB status to diagnose high thread concurrency."
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
if ! innodb_status=$($MYSQL -e "SHOW ENGINE INNODB STATUS\G" 2>&1); then
    echo "Could not retrieve InnoDB status (check --defaults-file): $innodb_status"
else
    printf '%s\n' "$innodb_status" | head -150 || true
fi

echo ""
echo "********* System load *********"
uptime
