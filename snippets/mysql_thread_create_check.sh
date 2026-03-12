#!/usr/bin/env bash

# ---
# title: "MySQL Thread Create Check"
# description: "This script checks thread cache hit rate, thread creation rate, and aborted clients to diagnose excessive thread creation."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# ---

# Usage: ./mysql_thread_create_check.sh [--defaults-file=path]

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

echo "********* Thread cache configuration *********"
$MYSQL -e "SHOW GLOBAL VARIABLES LIKE 'thread_cache_size';"

echo ""
echo "********* Thread status *********"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'Threads_%';"

echo ""
echo "********* Connection count *********"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'Connections';"

echo ""
echo "********* Aborted clients (connection drops) *********"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'Aborted_clients';"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'Aborted_connects';"
