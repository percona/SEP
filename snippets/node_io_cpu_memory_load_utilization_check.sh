#!/usr/bin/env bash

# ---
# title: "Node IO/CPU/Load/Memory Utilization Check"
# description: "This script outputs I/O, CPU, load, and memory utilization of system to assist in troubleshooting high system load scenarios."
# allow_extra_args: false
# sudo: always
# service_type: generic
# alerts:
#   - HighCPUUsage
#   - HighMemoryUsage
#   - HighIOUtilization
#   - name: MySQLTooManyThreadsRunning
#     service_type: mysql
#   - name: MySQLPXCFlowControl
#     service_type: mysql
#   - name: MySQLReplicaLag
#     service_type: mysql
#   - name: MongoDBHighFlowControl
#     service_type: mongodb
#   - name: MongoDBTicketExhaustion
#     service_type: mongodb
#   - name: MongoDBHighCacheMissRatio
#     service_type: mongodb
#   - name: MongoDBHighHeapUsage
#     service_type: mongodb
#   - name: MongoDBReadWriteQueueHigh
#     service_type: mongodb
#   - name: PostgreSQLTransactionDuration
#     service_type: postgresql
#   - name: PostgreSQLTooManyLocksAcquired
#     service_type: postgresql
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
section "I/O utilization"
if command -v iotop &> /dev/null; then
    iotop -o -b -n10
else
    echo "iotop not found, please install to view I/O utilization."
fi

# Display memory statistics
section "Memory statistics"
section "Virtual memory statistics"
if command -v vmstat &> /dev/null; then
    vmstat -t -n 1 10
else
    echo "vmstat not found, please install to view virtual memory statistics."
fi
section "Top memory-consuming processes (ps)"
ps aux --sort=-%mem | head -n 20
section "Top memory-consuming processes (top)"
top -b -n1 -o %MEM | head -n 40
