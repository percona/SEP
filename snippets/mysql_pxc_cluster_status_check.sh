#!/usr/bin/env bash

# ---
# title: "PXC Cluster Status Check"
# description: "This script checks PXC cluster status, quorum, and node connectivity to diagnose cluster split-brain or non-primary state."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# ---

# Usage: ./mysql_pxc_cluster_status_check.sh [--defaults-file=path]

set -euo pipefail

DEFAULTS_FILE=""
if [[ "${1:-}" == --defaults-file=* ]]; then
    DEFAULTS_FILE="$1"
    shift
elif [[ "${1:-}" == --defaults-file ]]; then
    DEFAULTS_FILE="--defaults-file=${2}"
    shift 2
fi

MYSQL="mysql $DEFAULTS_FILE -B"

echo "********* Cluster status *********"
echo ""
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_cluster_status';"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_connected';"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_cluster_size';"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_ready';"

echo ""
echo "********* Local node state *********"
echo ""
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_local_state_comment';"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_local_state';"

echo ""
echo "********* Cluster member UUIDs *********"
echo ""
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_cluster_state_uuid';"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_local_state_uuid';"

echo ""
echo "********* Incoming addresses (visible cluster members) *********"
echo ""
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_incoming_addresses';"

echo ""
echo "********* MySQL service status *********"
echo ""
systemctl status mysql --no-pager 2> /dev/null \
    || systemctl status mysqld --no-pager 2> /dev/null \
    || echo "MySQL service status not available."

echo ""
echo "********* Recent MySQL error log (wsrep entries) *********"
echo ""
ERROR_LOG=$($MYSQL -N -e "SELECT @@log_error;" 2> /dev/null) || true
if [ -n "${ERROR_LOG:-}" ] && [ -f "$ERROR_LOG" ]; then
    grep -i "wsrep\|quorum\|non-primary\|split.brain" "$ERROR_LOG" | tail -30
else
    echo "MySQL error log not accessible."
fi
