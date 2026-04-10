#!/usr/bin/env bash

# ---
# title: "PXC Wsrep Desync Check"
# description: "This script checks PXC node synchronization state, wsrep_desync variable, and cluster status to diagnose desync issues."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# service_type: mysql
# alerts:
#   - MySQLPXCWsrepDesync
# ---

# Usage: ./mysql_pxc_wsrep_desync_check.sh [--defaults-file=path]

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

echo "********* Wsrep local state *********"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'wsrep_local_state_comment';"

echo ""
echo "********* Wsrep desync variable *********"
$MYSQL -e "SELECT @@global.wsrep_desync;"
