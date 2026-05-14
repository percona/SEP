#!/usr/bin/env bash

# ---
# title: "MySQL Instance Not Available Check"
# description: "This script checks MySQL service status, error logs, and system logs to diagnose MySQL availability or restart issues."
# allow_extra_args: false
# sudo: always
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# service_type: mysql
# alerts:
#   - MySQLInstanceNotAvailable
# ---

# Usage: ./mysql_instance_not_available_check.sh [--defaults-file=path]

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

echo "********* MySQL service status *********"
systemctl status mysqld --no-pager 2> /dev/null ||
    systemctl status mysql --no-pager 2> /dev/null ||
    echo "MySQL service not found."

echo ""
echo "********* MySQL processes *********"
pgrep -a -x "mysqld" || echo "No mysqld processes found."

echo ""
echo "********* MySQL uptime (if accessible) *********"
$MYSQL -e "SHOW GLOBAL STATUS LIKE 'Uptime';" 2> /dev/null || echo "Cannot connect to MySQL."

echo ""
echo "********* MySQL error log (last 50 lines) *********"
ERROR_LOG=$($MYSQL -N -e "SELECT @@log_error;" 2> /dev/null) || true
if [ -n "${ERROR_LOG:-}" ] && [ -f "$ERROR_LOG" ]; then
    tail -50 "$ERROR_LOG"
else
    for logpath in /var/log/mysql/error.log /var/log/mysqld.log /var/log/mysql/mysqld.log; do
        if [ -f "$logpath" ]; then
            echo "Found: $logpath"
            tail -50 "$logpath"
            break
        fi
    done || echo "MySQL error log not found."
fi

echo ""
echo "********* OOM killer events (dmesg) *********"
dmesg -T 2> /dev/null | grep -i "oom\|out of memory\|killed process" | tail -10 ||
    echo "No OOM events found or dmesg not accessible."

echo ""
echo "********* System log errors *********"
tail -30 /var/log/syslog 2> /dev/null | grep -i "mysql\|oom\|kill" ||
    tail -30 /var/log/messages 2> /dev/null | grep -i "mysql\|oom\|kill" ||
    echo "No relevant entries in system logs."
