#!/usr/bin/env bash

# ---
# title: "MySQL IP Controller Check"
# description: "This script checks the ip_controller process and logs to diagnose VIP assignment issues for MySQL clusters."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mysql_ip_controller_check.sh

set -euo pipefail

echo "********* IP controller process *********"
ps -ef | grep -i "[i]p_controller" || echo "No ip_controller processes found."

echo ""
echo "********* IP controller logs *********"
for logfile in ~/.local/percona/ip_controller_*.log; do
    if [ -f "$logfile" ]; then
        echo "--- $(basename "$logfile") (last 50 lines) ---"
        tail -50 "$logfile"
        echo ""
    fi
done || echo "No ip_controller logs found in ~/.local/percona/"

echo ""
echo "********* GAS tools version *********"
if [ -f /home/percona/bin/gas-tools ]; then
    /home/percona/bin/gas-tools 2> /dev/null | head -1 || true
else
    echo "gas-tools not found."
fi

echo ""
echo "********* crontab entries for ip_controller *********"
crontab -l 2> /dev/null | grep -i "ip_controller" || echo "No ip_controller crontab entries found."
