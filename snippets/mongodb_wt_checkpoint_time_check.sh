#!/usr/bin/env bash

# ---
# title: "MongoDB WiredTiger Checkpoint Time Check"
# description: "This script checks WiredTiger checkpoint duration and disk performance to diagnose high checkpoint times."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mongodb_wt_checkpoint_time_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* WiredTiger checkpoint info *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
var txn = ss.wiredTiger.transaction;
print('transaction checkpoint currently running: ' + (txn['transaction checkpoint currently running'] || 'N/A'));
print('transaction checkpoint generation: ' + (txn['transaction checkpoint generation'] || 'N/A'));
print('transaction checkpoint max time (msecs): ' + (txn['transaction checkpoint max time (msecs)'] || 'N/A'));
print('transaction checkpoint min time (msecs): ' + (txn['transaction checkpoint min time (msecs)'] || 'N/A'));
print('transaction checkpoint most recent time (msecs): ' + (txn['transaction checkpoint most recent time (msecs)'] || 'N/A'));
print('transaction checkpoint total time (msecs): ' + (txn['transaction checkpoint total time (msecs)'] || 'N/A'));
" 2> /dev/null || echo "Cannot retrieve WiredTiger checkpoint info."

echo ""
echo "********* WiredTiger cache status *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
var cache = ss.wiredTiger.cache;
print('bytes currently in cache: ' + cache['bytes currently in the cache']);
print('maximum bytes configured: ' + cache['maximum bytes configured']);
print('tracked dirty bytes: ' + cache['tracked dirty bytes in the cache']);
" 2> /dev/null || true

echo ""
echo "********* Recent checkpoint log entries *********"
echo ""
journalctl -u mongod --no-pager -n 200 2> /dev/null | grep -i "checkpoint" | tail -10 \
    || grep -i "checkpoint" /var/log/mongodb/mongod.log 2> /dev/null | tail -10 \
    || echo "No checkpoint log entries found."

echo ""
echo "********* Disk IO stats *********"
echo ""
if command -v iostat &> /dev/null; then
    iostat -xz 1 3 | tail -20
else
    echo "iostat not available."
fi
