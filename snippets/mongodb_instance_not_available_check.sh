#!/usr/bin/env bash

# ---
# title: "MongoDB Instance Not Available Check"
# description: "This script checks MongoDB service status and processes to diagnose instance availability issues."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mongodb_instance_not_available_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* MongoDB service status *********"
echo ""
systemctl status mongod --no-pager 2> /dev/null \
    || systemctl status mongos --no-pager 2> /dev/null \
    || echo "No mongod/mongos systemd service found."

echo ""
echo "********* MongoDB processes *********"
echo ""
ps -ef | grep "[m]ongo" || echo "No MongoDB processes found."

echo ""
echo "********* MongoDB listening ports *********"
echo ""
ss -lntp | grep mongo 2> /dev/null \
    || netstat -lntp 2> /dev/null | grep mongo \
    || echo "Could not check listening ports."
