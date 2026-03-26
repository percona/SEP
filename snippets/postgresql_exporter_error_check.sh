#!/usr/bin/env bash

# ---
# title: "PostgreSQL Exporter Error Check"
# description: "This script checks PMM agent and PostgreSQL exporter logs to diagnose exporter errors affecting monitoring."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./postgresql_exporter_error_check.sh

set -euo pipefail

echo "********* PMM agent service status *********"
echo ""
systemctl status pmm-agent --no-pager 2> /dev/null ||
    systemctl status pmm-agent --user --no-pager 2> /dev/null ||
    echo "pmm-agent service not found."

echo ""
echo "********* PMM agent log errors *********"
echo ""
journalctl -u pmm-agent --no-pager -n 100 2> /dev/null | { grep -i "error\|postgres" || true; } | tail -30 ||
    journalctl -u pmm-agent --user --no-pager -n 100 2> /dev/null | { grep -i "error\|postgres" || true; } | tail -30 ||
    echo "No pmm-agent journal logs found."

echo ""
echo "********* PMM server exporter logs (if on monitor host) *********"
echo ""
if command -v podman &> /dev/null; then
    podman exec pmm-server bash -c 'grep -i "error\|postgres" /srv/logs/pmm-agent.log 2> /dev/null | tail -30' 2> /dev/null ||
        echo "Could not access PMM server container logs."
elif command -v docker &> /dev/null; then
    docker exec pmm-server bash -c 'grep -i "error\|postgres" /srv/logs/pmm-agent.log 2> /dev/null | tail -30' 2> /dev/null ||
        echo "Could not access PMM server container logs."
else
    echo "Not a monitor host or container runtime not found."
fi

echo ""
echo "********* PostgreSQL exporter processes *********"
echo ""
ps aux | grep -i "[p]ostgres_exporter" || echo "No postgres_exporter processes found."
