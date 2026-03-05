#!/usr/bin/env bash

# ---
# title: "MongoDB WiredTiger Ticket Use Check"
# description: "This script checks WiredTiger read/write ticket availability to diagnose ticket exhaustion causing request queuing."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mongodb_wt_ticket_use_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* WiredTiger concurrent transactions (tickets) *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
var wt = ss.wiredTiger.concurrentTransactions;
print('read available:  ' + wt.read.available);
print('read out:        ' + wt.read.out);
print('read totalTickets: ' + wt.read.totalTickets);
print('write available: ' + wt.write.available);
print('write out:       ' + wt.write.out);
print('write totalTickets: ' + wt.write.totalTickets);
" 2> /dev/null || echo "Cannot retrieve WiredTiger ticket info."

echo ""
echo "********* WiredTiger cache status *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
var cache = ss.wiredTiger.cache;
print('bytes currently in cache: ' + cache['bytes currently in the cache']);
print('maximum bytes configured: ' + cache['maximum bytes configured']);
print('tracked dirty bytes in cache: ' + cache['tracked dirty bytes in the cache']);
" 2> /dev/null || true

echo ""
echo "********* Long-running operations *********"
echo ""
$MONGOSH --eval "
db.currentOp({'secs_running': {\$gt: 5}}).inprog.forEach(function(op) {
    print('OpID: ' + op.opid + '  secs: ' + op.secs_running + '  NS: ' + op.ns + '  plan: ' + (op.planSummary || 'N/A'));
});
" 2> /dev/null || echo "Cannot check currentOp."

echo ""
echo "********* System disk IO *********"
echo ""
if command -v iostat &> /dev/null; then
    iostat -xz 1 3 | tail -20
else
    echo "iostat not available."
fi
