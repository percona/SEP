#!/usr/bin/env bash

# ---
# title: "MongoDB Opcounters Check"
# description: "This script checks MongoDB operation counters to diagnose sudden spikes in insert/query/update/delete rates."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./mongodb_opcounters_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* Opcounters snapshot *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
var oc = ss.opcounters;
print('insert:  ' + oc.insert);
print('query:   ' + oc.query);
print('update:  ' + oc.update);
print('delete:  ' + oc.delete);
print('getmore: ' + oc.getmore);
print('command: ' + oc.command);
" 2> /dev/null || echo "Cannot retrieve server status."

echo ""
echo "********* Opcounters replication *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
if (ss.opcountersRepl) {
    var ocr = ss.opcountersRepl;
    print('repl insert:  ' + ocr.insert);
    print('repl query:   ' + ocr.query);
    print('repl update:  ' + ocr.update);
    print('repl delete:  ' + ocr.delete);
    print('repl getmore: ' + ocr.getmore);
    print('repl command: ' + ocr.command);
} else {
    print('opcountersRepl not available.');
}
" 2> /dev/null || true

echo ""
echo "********* Connection count *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
print('connections current: ' + ss.connections.current);
print('connections available: ' + ss.connections.available);
" 2> /dev/null || true

echo ""
echo "********* System uptime *********"
echo ""
uptime
