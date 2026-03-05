#!/usr/bin/env bash

# ---
# title: "MongoDB WiredTiger Dirty Ratio Check"
# description: "This script checks the WiredTiger dirty cache ratio and write throughput to diagnose cache pressure issues."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mongodb_wt_dirty_ratio_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* WiredTiger cache and dirty ratio *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
var cache = ss.wiredTiger.cache;
var total = cache['bytes currently in the cache'];
var dirty = cache['tracked dirty bytes in the cache'];
var maxBytes = cache['maximum bytes configured'];
var dirtyPct = (dirty / total * 100).toFixed(2);
print('cache bytes in use:    ' + total + ' (' + (total / 1024 / 1024 / 1024).toFixed(2) + ' GB)');
print('cache max configured:  ' + maxBytes + ' (' + (maxBytes / 1024 / 1024 / 1024).toFixed(2) + ' GB)');
print('dirty bytes in cache:  ' + dirty + ' (' + (dirty / 1024 / 1024 / 1024).toFixed(2) + ' GB)');
print('dirty ratio:           ' + dirtyPct + '%');
print('');
print('pages read into cache: ' + cache['pages read into cache']);
print('pages written from cache: ' + cache['pages written from cache']);
" 2> /dev/null || echo "Cannot retrieve WiredTiger cache info."

echo ""
echo "********* Opcounters (write volume) *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
var oc = ss.opcounters;
print('insert: ' + oc.insert);
print('update: ' + oc.update);
print('delete: ' + oc.delete);
" 2> /dev/null || true

echo ""
echo "********* Disk IO stats *********"
echo ""
if command -v iostat &> /dev/null; then
    iostat -xz 1 3 | tail -20
else
    echo "iostat not available."
fi
