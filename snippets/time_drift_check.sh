#!/usr/bin/env bash

# ---
# title: "Time Drift Check"
# descrption: "This script checks for time drift between database servers and PMM server and detects running NTP implementation."
# allow_extra_args: false
# sudo: optional
# service_type: generic
# alerts:
#   - TimeDrift
# ---

set -euo pipefail

# Check if timedatectl is reporting unsynchronized system clock and check for PMM admin time drift status
echo "System NTP synchronization status: $(timedatectl show -p NTPSynchronized --value)"
echo "PMM time drift: $(pmm-admin status --json | jq -M '.pmm_agent_status.server_clock_drift / 1000')" "μs"

# Report back on what NTP implementation the system is running
if systemctl is-active -q ntpd; then
    echo "ntpd is running."
elif systemctl is-active -q chronyd; then
    echo "chronyd is running."
elif systemctl is-active -q systemd-timesyncd; then
    echo "systemd-timesyncd is running."
else
    echo "Could not determine running NTP implementation or no NTP service is active."
    exit 1
fi
