#!/usr/bin/env bash

# ---
# title: "MongoDB Connections Check"
# description: "This script checks MongoDB connection stats by client, idle connections, and blocked operations to diagnose high connection counts."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mongodb_connections_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* Connection summary *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
print('current: ' + ss.connections.current);
print('available: ' + ss.connections.available);
print('totalCreated: ' + ss.connections.totalCreated);
print('active: ' + (ss.connections.active || 'N/A'));
" 2> /dev/null || echo "Cannot retrieve server status."

echo ""
echo "********* Connections by client IP *********"
echo ""
$MONGOSH --eval "
var out = db.getSiblingDB('admin').aggregate([
    { \$currentOp: { allUsers: true, idleConnections: true, idleSessions: true } },
    { \$project: {
        _id: 0,
        client: { \$arrayElemAt: [{ \$split: ['\$client', ':'] }, 0] },
        curr_active: { \$cond: [{ \$eq: ['\$active', true] }, 1, 0] },
        curr_inactive: { \$cond: [{ \$eq: ['\$active', false] }, 1, 0] }
    }},
    { \$match: { client: { \$ne: null } } },
    { \$group: { _id: '\$client', curr_active: { \$sum: '\$curr_active' }, curr_inactive: { \$sum: '\$curr_inactive' }, total: { \$sum: 1 } } },
    { \$sort: { total: -1 } }
]);
out.forEach(function(d) { printjson(d); });
" 2> /dev/null || echo "Cannot run currentOp aggregation."

echo ""
echo "********* Operations waiting for locks *********"
echo ""
$MONGOSH --eval "
db.currentOp({'waitingForLock': true}).inprog.forEach(function(op) {
    print('OpID: ' + op.opid + '  NS: ' + op.ns + '  Wait: ' + (op.microsecs_running / 1000) + 'ms  Cmd: ' + JSON.stringify(op.command));
});
" 2> /dev/null || echo "Cannot check currentOp."
