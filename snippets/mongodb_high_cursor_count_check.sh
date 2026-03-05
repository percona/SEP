#!/usr/bin/env bash

# ---
# title: "MongoDB High Cursor Count Check"
# description: "This script checks open cursor counts and identifies potential cursor leaks to diagnose high cursor count alerts."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mongodb_high_cursor_count_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* Cursor metrics *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
var cursors = ss.metrics.cursor;
print('open total:     ' + cursors.open.total);
print('open noTimeout: ' + cursors.open.noTimeout);
print('open pinned:    ' + cursors.open.pinned);
print('timed out:      ' + cursors.timedOut);
" 2> /dev/null || echo "Cannot retrieve cursor metrics."

echo ""
echo "********* Connection count *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
print('connections current:   ' + ss.connections.current);
print('connections available: ' + ss.connections.available);
" 2> /dev/null || true

echo ""
echo "********* Long-running operations (potential cursor holders) *********"
echo ""
$MONGOSH --eval "
db.currentOp({'secs_running': {\$gt: 30}}).inprog.forEach(function(op) {
    print('OpID: ' + op.opid + '  secs: ' + op.secs_running + '  NS: ' + op.ns + '  plan: ' + (op.planSummary || 'N/A'));
});
" 2> /dev/null || echo "Cannot check currentOp."

echo ""
echo "********* System open file descriptors *********"
echo ""
MONGOD_PID=$(pgrep -x mongod 2> /dev/null | head -1) || true
if [ -n "${MONGOD_PID:-}" ]; then
    echo "mongod PID: $MONGOD_PID"
    ls /proc/"$MONGOD_PID"/fd 2> /dev/null | wc -l || echo "Cannot count open FDs."
else
    echo "mongod process not found."
fi
