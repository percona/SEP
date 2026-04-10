#!/usr/bin/env bash

# ---
# title: "MongoDB High Heap Usage Check"
# description: "This script checks MongoDB tcmalloc heap memory usage and provides diagnostics for high heap consumption."
# allow_extra_args: false
# sudo: optional
# service_type: mongodb
# alerts:
#   - MongoDBHighHeapUsage
# ---

# Usage: ./mongodb_high_heap_usage_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* tcmalloc memory stats *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
var tcm = ss.tcmalloc;
if (tcm && tcm.generic) {
    print('current_allocated_bytes: ' + tcm.generic.current_allocated_bytes + ' (' + (tcm.generic.current_allocated_bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB)');
    print('heap_size:               ' + tcm.generic.heap_size + ' (' + (tcm.generic.heap_size / 1024 / 1024 / 1024).toFixed(2) + ' GB)');
}
if (tcm && tcm.tcmalloc) {
    var t = tcm.tcmalloc;
    function fmt(v) { return v != null ? v : 'N/A'; }
    var phfb = t.pageheap_free_bytes;
    print('pageheap_free_bytes:     ' + fmt(phfb) + (typeof phfb === 'number' ? ' (' + (phfb / 1024 / 1024 / 1024).toFixed(2) + ' GB)' : ''));
    print('central_cache_free_bytes: ' + fmt(t.central_cache_free_bytes));
    print('thread_cache_free_bytes: ' + fmt(t.thread_cache_free_bytes));
    print('aggressive_memory_decommit: ' + fmt(t.aggressive_memory_decommit));
}
" 2> /dev/null || echo "Cannot retrieve tcmalloc stats."

echo ""
echo "********* tcmalloc formatted string *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
if (ss.tcmalloc && ss.tcmalloc.tcmalloc && ss.tcmalloc.tcmalloc.formattedString) {
    print(ss.tcmalloc.tcmalloc.formattedString);
} else {
    print('formattedString not available.');
}
" 2> /dev/null || true

echo ""
echo "********* WiredTiger cache size *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
var cache = ss.wiredTiger.cache;
print('cache max configured: ' + (cache['maximum bytes configured'] / 1024 / 1024 / 1024).toFixed(2) + ' GB');
print('cache bytes in use:   ' + (cache['bytes currently in the cache'] / 1024 / 1024 / 1024).toFixed(2) + ' GB');
" 2> /dev/null || true

echo ""
echo "********* System memory *********"
echo ""
free -h

echo ""
echo "********* MongoDB process memory *********"
echo ""
MONGOD_PID="$(pgrep -x mongod 2> /dev/null | head -1 || true)"
if [[ -n ${MONGOD_PID} ]]; then
    ps -o pid,rss,vsz,comm -p "${MONGOD_PID}" 2> /dev/null || echo "mongod process not found."
else
    echo "mongod process not found."
fi
