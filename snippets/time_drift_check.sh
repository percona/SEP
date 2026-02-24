#!/usr/bin/env bash

# ---
# title: "Time Drift Check"
# descrption: "This script checks for time drift between database servers and PMM server and detects running NTP implementation."
# allow_extra_args: false
# sudo: optional
# ---

# Check if timedatectl is reporting unsynchronized system clock
# and check for PMM admin time drift status 
timedatectl | grep --color=never -B1 'System clock synchronized: no'
pmm-admin status | grep --color=never 'Time drift'

# Check for running NTP implementation on system in order to proceed
if command -v systemctl &> /dev/null; then
    if systemctl is-active -q ntpd; then
        echo "ntpd is running"
        exit 0
    elif systemctl is-active -q chronyd; then
        echo "chronyd is running"
        exit 0
    elif systemctl is-active -q systemd-timesyncd; then
        echo "systemd-timesyncd is running"
        exit 0
    fi
fi

echo "Could not determine running NTP implementation or no NTP service is active."
exit 1
