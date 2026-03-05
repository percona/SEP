#!/usr/bin/env bash

# ---
# title: "MongoDB Replica State/No Primary Check"
# description: "This script checks replica set health and member states to diagnose members in UNKNOWN, RECOVERING, or REMOVED state, or loss of primary in a MongoDB cluster."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mongodb_repl_state_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* Replica set status *********"
echo ""
$MONGOSH --eval "printjson(rs.status())" 2> /dev/null || echo "Cannot connect to MongoDB or not a replica set."

echo "********* Replica set member states *********"
echo ""
$MONGOSH --eval "
var status = rs.status();
status.members.forEach(function(m) {
    print('name: ' + m.name + '  state: ' + m.stateStr + '  health: ' + m.health + '  uptime: ' + m.uptime + 's  lastHeartbeat: ' + (m.lastHeartbeat || 'self'));
});
" 2> /dev/null || echo "Cannot retrieve replica set status."

echo ""
echo "********* Replica set configuration *********"
echo ""
$MONGOSH --eval "printjson(rs.conf())" 2> /dev/null || true

echo ""
echo "********* MongoDB service status *********"
echo ""
systemctl status mongod --no-pager 2> /dev/null \
    || systemctl status mongos --no-pager 2> /dev/null \
    || echo "No mongod/mongos systemd service found."

echo ""
echo "********* MongoDB processes *********"
echo ""
ps -ef | grep "[m]ongo" || echo "No MongoDB processes found."

echo ""
echo "********* Recent MongoDB log entries (replication state) *********"
echo ""
journalctl -u mongod --no-pager -n 200 2> /dev/null | grep -i "stale\|oplog\|too stale\|RECOVERING\|REMOVED\|UNKNOWN\|not reachable\|replSet" | tail -30 \
    || grep -i "stale\|oplog\|too stale\|RECOVERING\|REMOVED\|UNKNOWN\|not reachable\|replSet" /var/log/mongodb/mongod.log 2> /dev/null | tail -30 \
    || echo "No relevant log entries found."

echo ""
echo "********* Recent MongoDB log entries (elections, errors) *********"
echo ""
journalctl -u mongod --no-pager -n 200 2> /dev/null | grep -i "election\|primary\|quorum\|not reachable\|down\|error" | tail -30 \
    || grep -i "election\|primary\|quorum\|not reachable\|down\|error" /var/log/mongodb/mongod.log 2> /dev/null | tail -30 \
    || echo "No relevant log entries found."

echo ""
echo "********* Oplog info *********"
echo ""
$MONGOSH --eval "printjson(db.getReplicationInfo())" 2> /dev/null || true
