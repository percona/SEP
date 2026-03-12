#!/usr/bin/env bash

# ---
# title: "HostGroup No Online Server Check"
# description: "This script checks ProxySQL runtime server status to identify hostgroups with no online backend servers."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# ---

# Usage: ./mysql_hostgroup_no_online_server_check.sh [--defaults-file=path]

set -euo pipefail

DEFAULTS_FILE=""
if [[ "${1:-}" == --defaults-file=* ]]; then
    DEFAULTS_FILE="$1"
    shift
elif [[ "${1:-}" == --defaults-file ]]; then
    DEFAULTS_FILE="--defaults-file=${2}"
    shift 2
fi

PROXYSQL="mysql -u admin -h 127.0.0.1 -P 6032 $DEFAULTS_FILE"

echo "********* ProxySQL runtime server status *********"
$PROXYSQL -e "SELECT * FROM runtime_mysql_servers;" 2> /dev/null \
    || echo "Cannot connect to ProxySQL admin interface."
