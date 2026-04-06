#!/usr/bin/env bash
# shellcheck disable=SC2086

# ---
# title: "Group Replication queries"
# description: "Prints Group Replication diagnostics from performance_schema. Extra args are passed to mysql (e.g. -u, -p, SSL options)."
# allow_extra_args: true
# extra_args_placeholder: "e.g. -h 127.0.0.1 -u monitor"
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
#    arg_format: --defaults-file=${value}
# atw:
#  - GROUP_REPLICATION
# ---

# Usage: ./mysql_gr_queries.sh [--defaults-file=path] [mysql_args...]
# Example: ./mysql_gr_queries.sh --defaults-file=/etc/mysql/my.cnf -uroot -p

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

echo "Query: replication_group_member_stats"
$MYSQL "$@" -e "select * from performance_schema.replication_group_member_stats;"
echo

echo "Query: replication_group_members"
$MYSQL "$@" -e "select * from performance_schema.replication_group_members;"
echo

echo "Query: replication_group_communication_information"
$MYSQL "$@" -e "select * from performance_schema.replication_group_communication_information;"
echo

echo "Query: replication_connection_status"
$MYSQL "$@" -e "select * from performance_schema.replication_connection_status;"
echo

echo "Query: replication_applier_status"
$MYSQL "$@" -e "select * from performance_schema.replication_applier_status;"
echo
