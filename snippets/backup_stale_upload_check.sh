#!/usr/bin/env bash

# ---
# title: "Stale (Binary Log) Upload Check"
# description: "This script checks backup upload logs, binary log upload logs, and S3 upload status to diagnose stale or failed (binary log) uploads."

# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./backup_stale_upload_check.sh

set -euo pipefail

BACKUP_LOG_DIR="/var/log/percona/backups"

echo "********* Recent upload log *********"
echo ""
if [ -f "$BACKUP_LOG_DIR/upload.log" ]; then
    tail -n 100 "$BACKUP_LOG_DIR/upload.log"
else
    echo "upload.log not found at $BACKUP_LOG_DIR"
fi

echo ""
echo "********* Latest S3 upload logs *********"
echo ""
ls -alhrt "$BACKUP_LOG_DIR" 2> /dev/null | grep -E "s3cmd-" | tail -n 4 \
    || echo "No S3 upload logs found."

echo ""
echo "********* Latest S3 binary log upload logs *********"
echo ""
ls -alhrt "$BACKUP_LOG_DIR" 2> /dev/null | grep -E "s3cmd-.*-B-" | tail -n 4 \
    || echo "No S3 binary log upload logs found."

echo ""
echo "********* Errors in recent upload logs *********"
echo ""
if [ -f "$BACKUP_LOG_DIR/upload.log" ]; then
    grep -i "error\|fail\|denied\|timeout" "$BACKUP_LOG_DIR/upload.log" | tail -20 \
        || echo "No errors found in upload.log."
else
    echo "upload.log not found."
fi

echo ""
echo "********* Running xtrabackup/mydumper upload processes *********"
echo ""
ps aux | grep -E "[s]3cmd|[u]pload" | head -10 || echo "No upload processes currently running."
