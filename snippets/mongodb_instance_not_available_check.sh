#!/usr/bin/env bash

# ---
# title: "MongoDB Instance Not Available Check"
# description: "This script checks MongoDB service status and processes to diagnose instance availability issues."
# allow_extra_args: false
# sudo: optional
# service_type: mongodb
# alerts:
#   - MongoDBInstanceNotAvailable
# ---

# Usage: ./mongodb_instance_not_available_check.sh

set -euo pipefail

echo "********* MongoDB service status *********"
echo ""
systemctl status mongod --no-pager 2> /dev/null ||
    systemctl status mongos --no-pager 2> /dev/null ||
    echo "No mongod/mongos systemd service found."

echo ""
echo "********* MongoDB processes *********"
echo ""
MONGO_PROCS="$({
    pgrep -xa mongod 2> /dev/null
    pgrep -xa mongos 2> /dev/null
} || true)"
if [[ -n ${MONGO_PROCS} ]]; then
    echo "${MONGO_PROCS}"
else
    echo "No MongoDB processes found."
fi

echo ""
echo "********* MongoDB listening ports *********"
echo ""
ss -lntp | grep mongo 2> /dev/null ||
    netstat -lntp 2> /dev/null | grep mongo ||
    echo "Could not check listening ports."
