#!/usr/bin/env bash

# ---
# title: "Show Replica Status"
# description: "Prints the output of SHOW REPLICA STATUS. Extra args are passed to mysql (e.g. -u, -p, SSL options)."
# allow_extra_args: true
# extra_args_placeholder: "e.g. -h 127.0.0.1 -u monitor"
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# atw:
#  - NATIVE_ASYNC_REPLICATION
#  - MULTI_SOURCE_REPLICATION
# service_type: mysql
# alerts:
#   - MySQLReplicaLag
# ---

# Usage: ./mysql_replica_status.sh [--defaults-file=path] [mysql_args...]
# Example: ./mysql_replica_status.sh --defaults-file=/etc/mysql/my.cnf -uroot -p

# Check for --defaults-file argument
DEFAULTS_FILE=""
if [[ $1 == --defaults-file=* ]]; then
    DEFAULTS_FILE="$1"
    shift
elif [[ $1 == --defaults-file ]]; then
    DEFAULTS_FILE="--defaults-file=${2}"
    shift 2
fi

MYSQL="mysql $DEFAULTS_FILE -B"

# Try SHOW REPLICA STATUS and check for error anywhere in output
if ! $MYSQL "$@" -e 'SHOW REPLICA STATUS\G' 2>&1 | grep -q "You have an error"; then
    $MYSQL "$@" -e 'SHOW REPLICA STATUS\G'
else
    $MYSQL "$@" -e 'SHOW SLAVE STATUS\G'
fi
