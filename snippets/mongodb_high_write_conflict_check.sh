#!/usr/bin/env bash

# ---
# title: "MongoDB High Write Conflict Check"
# description: "This script checks MongoDB write conflict metrics and identifies hot collections to diagnose write contention."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mongodb_high_write_conflict_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* Write conflict metrics *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
if (ss.metrics && ss.metrics.operation) {
    print('writeConflicts: ' + (ss.metrics.operation.writeConflicts || 0));
}
if (ss.locks) {
    print('');
    print('Global lock stats:');
    printjson(ss.locks.Global);
}
" 2> /dev/null || echo "Cannot retrieve server status."

echo ""
echo "********* Active write operations *********"
echo ""
$MONGOSH --eval "
db.currentOp({'op': {\$in: ['insert', 'update', 'delete']}, 'secs_running': {\$gt: 2}}).inprog.forEach(function(op) {
    print('OpID: ' + op.opid + '  op: ' + op.op + '  secs: ' + op.secs_running + '  NS: ' + op.ns);
});
" 2> /dev/null || echo "Cannot check currentOp."

echo ""
echo "********* Top collections by activity (mongotop-style) *********"
echo ""
$MONGOSH --eval "
var top = db.adminCommand({top: 1});
if (top.totals) {
    var entries = [];
    for (var ns in top.totals) {
        if (ns !== 'note') {
            var t = top.totals[ns];
            entries.push({ns: ns, total: t.total.time, write: t.writeLock.time, read: t.readLock.time});
        }
    }
    entries.sort(function(a, b) { return b.write - a.write; });
    entries.slice(0, 10).forEach(function(e) {
        print(e.ns + '  total: ' + e.total + 'us  write: ' + e.write + 'us  read: ' + e.read + 'us');
    });
}
" 2> /dev/null || echo "Cannot retrieve top stats."

echo ""
echo "********* Open transactions *********"
echo ""
$MONGOSH --eval "
var txns = db.currentOp({'transaction': {\$exists: true}}).inprog;
if (txns.length > 0) {
    txns.forEach(function(op) {
        print('OpID: ' + op.opid + '  secs: ' + op.secs_running + '  NS: ' + op.ns + '  txn: ' + JSON.stringify(op.transaction).substring(0, 100));
    });
} else {
    print('No open transactions found.');
}
" 2> /dev/null || true
