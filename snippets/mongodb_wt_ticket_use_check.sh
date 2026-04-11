#!/usr/bin/env bash

# ---
# title: "MongoDB WiredTiger Ticket Use Check"
# description: "This script checks WiredTiger read/write ticket availability to diagnose ticket exhaustion causing request queuing."
# allow_extra_args: false
# sudo: optional
# service_type: mongodb
# alerts:
#   - MongoDBTicketExhaustion
# ---

# Usage: ./mongodb_wt_ticket_use_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* WiredTiger concurrent transactions (tickets) *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
function dumpTickets(label, t) {
    if (!t) { print(label + ' tickets not available.'); return; }
    print(label + ' available:    ' + (t.available != null ? t.available : 'N/A'));
    print(label + ' out:          ' + (t.out != null ? t.out : 'N/A'));
    print(label + ' totalTickets: ' + (t.totalTickets != null ? t.totalTickets : 'N/A'));
}
if (ss.queues && ss.queues.execution) {
    dumpTickets('read ', ss.queues.execution.read);
    dumpTickets('write', ss.queues.execution.write);
} else if (ss.wiredTiger && ss.wiredTiger.concurrentTransactions) {
    var wt = ss.wiredTiger.concurrentTransactions;
    dumpTickets('read ', wt.read);
    dumpTickets('write', wt.write);
} else {
    print('Ticket metrics not available in serverStatus.');
}
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
