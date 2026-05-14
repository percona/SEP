#!/usr/bin/env bash

# ---
# title: "MongoDB Inconsistent Indexes Check"
# description: "This script checks for inconsistent indexes across shards in a sharded MongoDB cluster."
# allow_extra_args: false
# sudo: optional
# service_type: mongodb
# alerts:
#   - MongoDBInconsistentIndexes
# ---

# Usage: ./mongodb_inconsistent_indexes_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* Sharded index consistency *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
if (ss.shardedIndexConsistency) {
    print('numShardedCollectionsWithInconsistentIndexes: ' + ss.shardedIndexConsistency.numShardedCollectionsWithInconsistentIndexes);
} else {
    print('shardedIndexConsistency not available (may not be a config server).');
}
" 2> /dev/null || echo "Cannot retrieve server status."

echo ""
echo "********* Metadata consistency check *********"
echo ""
$MONGOSH --eval "
var result = db.adminCommand({ checkMetadataConsistency: 1, checkIndexes: true });
var batch = [];
if (result.cursor) {
    if (Array.isArray(result.cursor.firstBatch)) {
        batch = result.cursor.firstBatch;
    } else if (Array.isArray(result.cursor.nextBatch)) {
        batch = result.cursor.nextBatch;
    }
}
if (batch.length > 0) {
    batch.forEach(function(item) {
        printjson(item);
    });
} else if (result.cursor) {
    print('No inconsistencies found.');
} else {
    print('checkMetadataConsistency did not return a cursor document:');
    printjson(result);
}
" 2> /dev/null || echo "Cannot run checkMetadataConsistency (requires MongoDB 7.0+ or config server)."

echo ""
echo "********* Shard status *********"
echo ""
$MONGOSH --eval "sh.status()" 2> /dev/null || echo "Cannot retrieve shard status (not a mongos?)."
