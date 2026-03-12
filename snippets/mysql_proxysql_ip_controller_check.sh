#!/usr/bin/env bash

# ---
# title: "ProxySQL IP Controller Check"
# description: "This script checks the ProxySQL ip_controller process and logs to diagnose VIP assignment issues for ProxySQL nodes."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mysql_proxysql_ip_controller_check.sh

set -euo pipefail

echo "********* ProxySQL IP controller process *********"
ps -ef | grep -i "[p]roxysql_ip_con" || echo "No proxysql_ip_controller processes found."

echo ""
echo "********* ProxySQL IP controller logs *********"
for logfile in ~/.local/percona/proxysql_ip_controller_*.log; do
    if [ -f "$logfile" ]; then
        echo "--- $(basename "$logfile") (last 50 lines) ---"
        tail -50 "$logfile"
        echo ""
    fi
done || echo "No proxysql_ip_controller logs found in ~/.local/percona/"

echo ""
echo "********* GAS tools version *********"
if [ -f /home/percona/bin/gas-tools ]; then
    /home/percona/bin/gas-tools 2> /dev/null | head -1 || true
else
    echo "gas-tools not found."
fi

echo ""
echo "********* crontab entries for proxysql_ip_controller *********"
crontab -l 2> /dev/null | grep -i "proxysql_ip_con" || echo "No proxysql_ip_controller crontab entries found."
