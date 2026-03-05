#!/usr/bin/env bash

# ---
# title: "MongoDB Replication Lag Check"
# description: "This script checks replication lag between primary and secondaries using replica set status."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mongodb_repl_lag_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* Replica set member lag *********"
echo ""
$MONGOSH --eval "
var status = rs.status();
var primary = null;
status.members.forEach(function(m) {
    if (m.stateStr === 'PRIMARY') primary = m;
});
if (primary) {
    print('Primary: ' + primary.name + '  optime: ' + tojson(primary.optimeDate));
    status.members.forEach(function(m) {
        if (m.stateStr !== 'PRIMARY') {
            var lagMs = primary.optimeDate - m.optimeDate;
            print('  ' + m.name + '  state: ' + m.stateStr + '  lag: ' + (lagMs / 1000) + 's  optime: ' + tojson(m.optimeDate));
        }
    });
} else {
    print('No PRIMARY found in replica set.');
    status.members.forEach(function(m) {
        print('  ' + m.name + '  state: ' + m.stateStr + '  health: ' + m.health);
    });
}
" 2> /dev/null || echo "Cannot retrieve replica set status."

echo ""
echo "********* Replication info (oplog) *********"
echo ""
$MONGOSH --eval "printjson(db.getReplicationInfo())" 2> /dev/null || true

echo ""
echo "********* Current operations on primary *********"
echo ""
$MONGOSH --eval "
db.currentOp({'secs_running': {\$gt: 10}}).inprog.forEach(function(op) {
    print('OpID: ' + op.opid + '  secs: ' + op.secs_running + '  NS: ' + op.ns + '  plan: ' + (op.planSummary || 'N/A'));
});
" 2> /dev/null || true

echo ""
echo "********* Disk IO on secondary *********"
echo ""
if command -v iostat &> /dev/null; then
    iostat -xz 1 3 | tail -15
else
    echo "iostat not available."
fi
