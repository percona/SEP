#!/usr/bin/env bash

# ---
# title: "PXC Flow Control Check"
# description: "This script checks PXC flow control status, receive queue, and applier thread configuration to diagnose flow control pauses."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# service_type: mysql
# alerts:
#   - MySQLPXCFlowControl
# ---

# Usage: ./mysql_pxc_flow_control_check.sh [--defaults-file=path]

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

echo "********* Flow control status *********"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_flow_control_paused';"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_flow_control_paused_ns';"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_flow_control_sent';"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_flow_control_recv';"

echo ""
echo "********* Receive queue status *********"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_local_recv_queue%';"

echo ""
echo "********* Applier thread configuration *********"
$MYSQL -e "SHOW GLOBAL VARIABLES LIKE 'wsrep_slave_threads';"

echo ""
echo "********* Cluster state *********"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_local_state_comment';"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_cluster_size';"

echo ""
echo "********* System I/O and CPU *********"
uptime
echo ""
if command -v iostat &> /dev/null; then
    iostat -xz 1 3 | tail -20
else
    echo "iostat not available."
fi
