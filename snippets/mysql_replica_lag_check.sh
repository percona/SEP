#!/usr/bin/env bash

# ---
# title: "MySQL Replica Lag Check"
# description: "This script checks replication lag, IO/SQL thread status, and parallel replication settings to diagnose replica lag."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# service_type: mysql
# alerts:
#   - MySQLReplicaLag
# ---

# Usage: ./mysql_replica_lag_check.sh [--defaults-file=path]

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

echo "********* Replica status *********"
if ! $MYSQL -e 'SHOW REPLICA STATUS\G' 2>&1 | grep -q "You have an error"; then
    $MYSQL -e 'SHOW REPLICA STATUS\G'
else
    $MYSQL -e 'SHOW SLAVE STATUS\G'
fi

echo ""
echo "********* Processlist *********"
$MYSQL -e "SHOW PROCESSLIST;" 2> /dev/null || echo "Cannot show processlist."
