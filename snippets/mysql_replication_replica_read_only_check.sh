#!/usr/bin/env bash

# ---
# title: "MySQL Replication/Replica Read Only Check"
# description: "This script checks replication thread status (IO/SQL), R/O status, identifies errors, and verifies connectivity to diagnose broken replication and/or write-enabled replicas."
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
for gtid_query in "SELECT @@server_uuid;" "SELECT @@gtid_mode;" "SELECT @@global.gtid_executed\G"; do
    if ! gtid_info=$($MYSQL -e "$gtid_query" 2>&1); then
        echo "Could not run '$gtid_query' (check --defaults-file): $gtid_info"
    else
        printf '%s\n' "$gtid_info"
    fi
done

echo ""
echo "********* Read-only status *********"
if ! read_only_status=$($MYSQL -e "SELECT @@global.read_only, @@global.super_read_only;" 2>&1); then
    echo "Could not read the read-only flags (check --defaults-file): $read_only_status"
else
    printf '%s\n' "$read_only_status"
fi
