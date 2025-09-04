#!/usr/bin/env bash

# ---
# title: "Show Replica Status"
# description: "Prints the output of SHOW REPLICA STATUS."
# allow_extra_args: true
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
#    arg_format: --defaults-file=${value}
# ---

# Usage: ./mysql_replica_status.sh [--defaults-file=path] [mysql_args...]
# Example: ./mysql_replica_status.sh --defaults-file=/etc/mysql/my.cnf -uroot -p

# Check for --defaults-file argument
DEFAULTS_FILE=""
if [[ $1 == --defaults-file=* ]]; then
    DEFAULTS_FILE="$1"
    shift
fi

MYSQL="mysql -B $DEFAULTS_FILE"

echo "Query: replication_group_member_stats"
$MYSQL -e "select * from performance_schema.replication_group_member_stats;"
echo

echo "Query: replication_group_members"
$MYSQL -e "select * from performance_schema.replication_group_members;"
echo

echo "Query: replication_group_communication_information"
$MYSQL -e "select * from performance_schema.replication_group_communication_information;"
echo

echo "Query: replication_connection_status"
$MYSQL -e "select * from performance_schema.replication_connection_status;"
echo

echo "Query: replication_applier_status"
$MYSQL -e "select * from performance_schema.replication_applier_status;"
echo
