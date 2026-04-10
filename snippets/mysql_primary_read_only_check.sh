#!/usr/bin/env bash

# ---
# title: "MySQL Primary Read-Only Check"
# description: "This script checks if a MySQL primary node has read_only enabled, which would block all write operations."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# service_type: mysql
# alerts:
#   - MySQLPrimaryReadOnly
# ---

# Usage: ./mysql_primary_read_only_check.sh [--defaults-file=path]

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

echo "********* Read-only settings *********"
$MYSQL -e "SELECT @@global.read_only AS read_only, @@global.super_read_only AS super_read_only;"

echo ""
echo "********* Server identity and uptime *********"
$MYSQL -e '\s' 2> /dev/null | head -10 || true
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'Uptime';"

echo ""
echo "********* Replication status (verify this is a primary) *********"
if ! $MYSQL -e 'SHOW REPLICA STATUS\G' 2>&1 | grep -q "You have an error"; then
    REPL=$($MYSQL -N -e 'SHOW REPLICA STATUS\G' 2> /dev/null) || true
else
    REPL=$($MYSQL -N -e 'SHOW SLAVE STATUS\G' 2> /dev/null) || true
fi
if [ -z "${REPL:-}" ]; then
    echo "No replication configured - this appears to be a primary/standalone."
else
    echo "Replication IS configured - verify this is actually a primary node."
    echo "$REPL" | grep -E "Running|Host|Behind" || true
fi

echo ""
echo "********* my.cnf read_only setting *********"
grep -i "read_only" /etc/mysql/my.cnf /etc/my.cnf /etc/mysql/mysql.conf.d/*.cnf 2> /dev/null ||
    echo "read_only not found in common config files."
