#!/usr/bin/env bash

# ---
# title: "MongoDB High Cache Miss Ratio Check"
# description: "This script checks WiredTiger cache miss ratio and identifies unindexed queries causing excessive disk reads."
# allow_extra_args: false
# sudo: optional
# service_type: mongodb
# alerts:
#   - MongoDBHighCacheMissRatio
# ---

# Usage: ./mongodb_high_cache_miss_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* WiredTiger cache stats *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
var cache = ss.wiredTiger.cache;
var total = cache['bytes currently in the cache'];
var maxBytes = cache['maximum bytes configured'];
var pagesRead = cache['pages read into cache'];
var pagesRequested = cache['pages requested from the cache'];
var missRatio = pagesRequested > 0 ? ((pagesRead / pagesRequested) * 100).toFixed(2) : 'N/A';
print('cache bytes in use:      ' + total + ' (' + (total / 1024 / 1024 / 1024).toFixed(2) + ' GB)');
print('cache max configured:    ' + maxBytes + ' (' + (maxBytes / 1024 / 1024 / 1024).toFixed(2) + ' GB)');
print('pages read into cache:   ' + pagesRead);
print('pages requested:         ' + pagesRequested);
print('cache miss ratio:        ' + missRatio + '%');
" 2> /dev/null || echo "Cannot retrieve WiredTiger cache info."

echo ""
echo "********* COLLSCAN queries (unindexed) *********"
echo ""
$MONGOSH --eval "
db.currentOp({'planSummary': 'COLLSCAN'}).inprog.forEach(function(op) {
    print('OpID: ' + op.opid + '  secs: ' + op.secs_running + '  NS: ' + op.ns);
});
" 2> /dev/null || echo "Cannot check for COLLSCAN queries."

echo ""
echo "********* Index sizes for current database *********"
echo ""
$MONGOSH --eval "
db.getCollectionNames().forEach(function(c) {
    var stats = db.getCollection(c).stats();
    print(c + ': totalIndexSize=' + stats.totalIndexSize + ' (' + (stats.totalIndexSize / 1024 / 1024).toFixed(2) + ' MB)');
});
" 2> /dev/null || echo "Cannot retrieve collection stats."

echo ""
echo "********* System memory *********"
echo ""
free -h
