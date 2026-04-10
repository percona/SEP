#!/usr/bin/env bash

# ---
# title: "MySQL Replication/Replica Read Only Check"
# description: "This script checks replication thread status (IO/SQL), R/O status, identifies errors, and verifies connectivity to diagnose broken replication and/or write-enabled replicas."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# service_type: mysql
# alerts:
#   - MySQLReplicationBroken
#   - MySQLReplicaReadOnlyDisabled
# ---

# Usage: ./mysql_replication_replica_read_only_check.sh [--defaults-file=path]

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
echo "********* Server UUID and GTID info *********"
$MYSQL -e "SELECT @@server_uuid;" 2> /dev/null || true
$MYSQL -e "SELECT @@gtid_mode;" 2> /dev/null || true
$MYSQL -e "SELECT @@global.gtid_executed\G" 2> /dev/null || true

echo ""
echo "********* Read-only status *********"
$MYSQL -e "SELECT @@global.read_only, @@global.super_read_only;" 2> /dev/null || true
