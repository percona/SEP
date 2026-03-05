#!/usr/bin/env bash

# ---
# title: "MongoDB Chunks Imbalance Check"
# description: "This script checks shard balancer state and chunk distribution to diagnose uneven data distribution across shards."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mongodb_chunks_imbalance_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* Balancer state *********"
echo ""
$MONGOSH --eval "print('Balancer enabled: ' + sh.getBalancerState())" 2> /dev/null || echo "Cannot check balancer state (not a mongos?)."

echo ""
echo "********* Balancer status *********"
echo ""
$MONGOSH --eval "printjson(sh.isBalancerRunning())" 2> /dev/null || true

echo ""
echo "********* Shard status (chunk distribution) *********"
echo ""
$MONGOSH --eval "sh.status()" 2> /dev/null || echo "Cannot retrieve shard status."

echo ""
echo "********* Recent balancer/moveChunk log entries *********"
echo ""
journalctl -u mongos --no-pager -n 200 2> /dev/null | grep -i "balancer\|moveChunk\|jumbo" | tail -20 \
    || grep -i "balancer\|moveChunk\|jumbo" /var/log/mongodb/mongos.log 2> /dev/null | tail -20 \
    || echo "No balancer log entries found."
