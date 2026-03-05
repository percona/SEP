#!/usr/bin/env bash

# ---
# title: "MongoDB Inconsistent Indexes Check"
# description: "This script checks for inconsistent indexes across shards in a sharded MongoDB cluster."
# allow_extra_args: false
# sudo: optional
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
if (result.firstBatch && result.firstBatch.length > 0) {
    result.firstBatch.forEach(function(item) {
        printjson(item);
    });
} else {
    print('No inconsistencies found.');
}
" 2> /dev/null || echo "Cannot run checkMetadataConsistency (requires MongoDB 7.0+ or config server)."

echo ""
echo "********* Shard status *********"
echo ""
$MONGOSH --eval "sh.status()" 2> /dev/null || echo "Cannot retrieve shard status (not a mongos?)."
