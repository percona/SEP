#!/usr/bin/env bash

# ---
# title: "ProxySQL Not Running Check"
# description: "This script checks ProxySQL service status, logs, and runtime server configuration to diagnose ProxySQL availability issues."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# ---

# Usage: ./mysql_proxysql_not_running_check.sh [--defaults-file=path]

set -euo pipefail

DEFAULTS_FILE=""
if [[ "${1:-}" == --defaults-file=* ]]; then
    DEFAULTS_FILE="$1"
    shift
elif [[ "${1:-}" == --defaults-file ]]; then
    DEFAULTS_FILE="--defaults-file=${2}"
    shift 2
fi

echo "********* ProxySQL service status *********"
echo ""
systemctl status proxysql --no-pager 2> /dev/null || echo "ProxySQL service not found."

echo ""
echo "********* ProxySQL process *********"
echo ""
ps aux | grep "[p]roxysql" || echo "No ProxySQL processes found."

echo ""
echo "********* Recent ProxySQL logs *********"
echo ""
tail -50 /var/lib/proxysql/proxysql.log 2> /dev/null \
    || echo "ProxySQL log not found at /var/lib/proxysql/proxysql.log"

echo ""
echo "********* ProxySQL admin connectivity and runtime servers *********"
echo ""
mysql -u admin -h 127.0.0.1 -P 6032 $DEFAULTS_FILE -e "SELECT * FROM runtime_mysql_servers;" 2> /dev/null \
    || echo "Cannot connect to ProxySQL admin interface on port 6032."
