#!/usr/bin/env bash

# ---
# title: "MongoDB Oplog Window Check"
# description: "This script checks the oplog window size and current oplog configuration to diagnose undersized oplog issues."
# allow_extra_args: false
# sudo: optional
# service_type: mongodb
# alerts:
#   - MongoDBOplogWindowLow
# ---

# Usage: ./mongodb_oplog_window_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* Replication info (oplog window) *********"
echo ""
$MONGOSH --eval "printjson(db.getReplicationInfo())" 2> /dev/null || echo "Cannot retrieve replication info."

echo ""
echo "********* Oplog collection stats *********"
echo ""
$MONGOSH --eval "
var stats = db.getSiblingDB('local').oplog.rs.stats();
print('storageSize: ' + stats.storageSize);
print('maxSize: ' + stats.maxSize);
print('count: ' + stats.count);
print('avgObjSize: ' + stats.avgObjSize);
" 2> /dev/null || echo "Cannot retrieve oplog stats."

echo ""
echo "********* Replica set member states *********"
echo ""
$MONGOSH --eval "
var status = rs.status();
status.members.forEach(function(m) {
    print('name: ' + m.name + '  state: ' + m.stateStr + '  health: ' + m.health);
});
" 2> /dev/null || true

echo ""
echo "********* Disk space *********"
echo ""
df -hP
