#!/usr/bin/env bash

# ---
# title: "MongoDB High Flow Control Check"
# description: "This script checks MongoDB flow control status and replication lag to diagnose write throttling on the primary."
# allow_extra_args: false
# sudo: optional
# service_type: mongodb
# alerts:
#   - MongoDBHighFlowControl
# ---

# Usage: ./mongodb_high_flow_control_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* Flow control status *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
function fmt(v) { return v != null ? v : 'N/A'; }
if (ss.flowControl) {
    var fc = ss.flowControl;
    print('enabled:                  ' + fmt(fc.enabled));
    print('isLagged:                 ' + fmt(fc.isLagged));
    print('isLaggedCount:            ' + fmt(fc.isLaggedCount));
    print('isLaggedTimeMicros:       ' + fmt(fc.isLaggedTimeMicros));
    print('targetRateLimit:          ' + fmt(fc.targetRateLimit));
    print('timeAcquiringMicros:      ' + fmt(fc.timeAcquiringMicros));
    print('locksPerKiloOp:           ' + fmt(fc.locksPerKiloOp));
    print('sustainerRate:            ' + fmt(fc.sustainerRate));
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
            var lagOutput = 'N/A';
            if (primary.optimeDate && m.optimeDate) {
                var lagMs = primary.optimeDate - m.optimeDate;
                if (!isNaN(lagMs)) {
                    lagOutput = (lagMs / 1000) + 's';
                }
            }
            print(m.name + '  state: ' + m.stateStr + '  lag: ' + lagOutput);
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
