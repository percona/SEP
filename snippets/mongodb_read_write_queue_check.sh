#!/usr/bin/env bash

# ---
# title: "MongoDB Read/Write Queue High Check"
# description: "This script checks global lock queues and identifies long-running or unindexed queries causing queue buildup."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mongodb_read_write_queue_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* Global lock queue *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
var gl = ss.globalLock;
print('currentQueue readers: ' + gl.currentQueue.readers);
print('currentQueue writers: ' + gl.currentQueue.writers);
print('currentQueue total: ' + gl.currentQueue.total);
print('activeClients readers: ' + gl.activeClients.readers);
print('activeClients writers: ' + gl.activeClients.writers);
print('activeClients total: ' + gl.activeClients.total);
" 2> /dev/null || echo "Cannot retrieve server status."

echo ""
echo "********* Long-running operations *********"
echo ""
$MONGOSH --eval "
db.currentOp({'secs_running': {\$gt: 10}}).inprog.forEach(function(op) {
    print('OpID: ' + op.opid + '  secs: ' + op.secs_running + '  NS: ' + op.ns + '  plan: ' + (op.planSummary || 'N/A') + '  Cmd: ' + JSON.stringify(op.command).substring(0, 120));
});
" 2> /dev/null || echo "Cannot check currentOp."

echo ""
echo "********* COLLSCAN queries (unindexed) *********"
echo ""
$MONGOSH --eval "
db.currentOp({'planSummary': 'COLLSCAN'}).inprog.forEach(function(op) {
    print('OpID: ' + op.opid + '  secs: ' + op.secs_running + '  NS: ' + op.ns + '  Cmd: ' + JSON.stringify(op.command).substring(0, 120));
});
" 2> /dev/null || echo "Cannot check for COLLSCAN queries."

echo ""
echo "********* Recent slow query log entries *********"
echo ""
journalctl -u mongod --no-pager -n 200 2> /dev/null | grep -i "Slow query\|COLLSCAN\|durationMillis" | tail -20 \
    || grep -i "Slow query\|COLLSCAN\|durationMillis" /var/log/mongodb/mongod.log 2> /dev/null | tail -20 \
    || echo "No slow query log entries found."
