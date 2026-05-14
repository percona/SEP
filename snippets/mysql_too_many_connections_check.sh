#!/usr/bin/env bash

# ---
# title: "MySQL Too Many Connections Check"
# description: "This script checks MySQL connection usage, identifies connection sources, and detects lock contention causing connection pileup."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
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
set +o pipefail
$MYSQL -e "SHOW ENGINE INNODB STATUS\G" 2> /dev/null | head -100
innodb_status_exit_code=${PIPESTATUS[0]}
set -o pipefail
if [[ ${innodb_status_exit_code} -ne 0 && ${innodb_status_exit_code} -ne 141 ]]; then
    echo "Cannot retrieve InnoDB status."
fi

echo ""
echo "********* Threads waiting for locks *********"
$MYSQL -e "SELECT * FROM information_schema.processlist WHERE state LIKE '%lock%' ORDER BY time DESC;" 2> /dev/null ||
    echo "No threads waiting for locks."
