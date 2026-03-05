#!/usr/bin/env bash

# ---
# title: "MongoDB High Flow Control Check"
# description: "This script checks MongoDB flow control status and replication lag to diagnose write throttling on the primary."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mongodb_high_flow_control_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* Flow control status *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
if (ss.flowControl) {
    print('enabled:                  ' + (ss.flowControl.enabled || 'N/A'));
    print('isLagged:                 ' + (ss.flowControl.isLagged || 'N/A'));
    print('isLaggedCount:            ' + (ss.flowControl.isLaggedCount || 'N/A'));
    print('isLaggedTimeMicros:       ' + (ss.flowControl.isLaggedTimeMicros || 'N/A'));
    print('targetRateLimit:          ' + (ss.flowControl.targetRateLimit || 'N/A'));
    print('timeAcquiringMicros:      ' + (ss.flowControl.timeAcquiringMicros || 'N/A'));
    print('locksPerKiloOp:           ' + (ss.flowControl.locksPerKiloOp || 'N/A'));
    print('sustainerRate:            ' + (ss.flowControl.sustainerRate || 'N/A'));
} else {
    print('flowControl not available in serverStatus.');
}
" 2> /dev/null || echo "Cannot retrieve server status."

echo ""
echo "********* Replication lag *********"
echo ""
$MONGOSH --eval "
var status = rs.status();
var primary = null;
status.members.forEach(function(m) {
    if (m.stateStr === 'PRIMARY') primary = m;
});
if (primary) {
    status.members.forEach(function(m) {
        if (m.stateStr !== 'PRIMARY') {
            var lagMs = primary.optimeDate - m.optimeDate;
            print(m.name + '  state: ' + m.stateStr + '  lag: ' + (lagMs / 1000) + 's');
        }
    });
} else {
    print('No PRIMARY found.');
}
" 2> /dev/null || true

echo ""
echo "********* Oplog window *********"
echo ""
$MONGOSH --eval "printjson(db.getReplicationInfo())" 2> /dev/null || true

echo ""
echo "********* Disk IO on secondaries *********"
echo ""
if command -v iostat &> /dev/null; then
    iostat -xz 1 3 | tail -15
else
    echo "iostat not available."
fi
