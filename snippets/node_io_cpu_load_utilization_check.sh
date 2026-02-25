#!/usr/bin/env bash

# ---
# title: "Node IO/CPU/Load Utilization Check"
# description: "This script outputs I/O, CPU, and load utilization of system to assist in troubleshooting high system load scenarios."
# allow_extra_args: false
# sudo: always
# ---

set -euo pipefail

section() {
    echo ""
    echo "********* $1 *********"
}

# Display CPU/load utilization
section "CPU/load utilization"

uptime
top -b -n10 | grep --color=never "load average" -A50

# Display I/O utilization
section "I/O Utilization"

if command -v iotop &>/dev/null; then
    iotop -o -b -n10
else
    echo "iotop not found, please install to view I/O utilization."
fi

# Display virtual memory statistics
section "Virtual memory statistics"

if command -v vmstat &>/dev/null; then
    vmstat -t -n 1 10
else
    echo "vmstat not found, please install to view virtual memory statistics."
fi
