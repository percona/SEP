#!/usr/bin/env bash

# ---
# title: "Stale (Binary Log) Upload Check"
# description: "This script checks backup upload logs, binary log upload logs, and S3 upload status to diagnose stale or failed (binary log) uploads."
# allow_extra_args: false
# sudo: optional
# service_type: mysql
# alerts:
#   - StaleUpload
#   - StaleUploadLog
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
s3cmd_logs=""
if [ -d "$BACKUP_LOG_DIR" ]; then
    s3cmd_logs=$(
        find "$BACKUP_LOG_DIR" -maxdepth 1 -type f \
            -name 's3cmd-*' \
            -printf '%T@ %TY-%Tm-%Td %TH:%TM %s %p\n' 2> /dev/null |
            sort -n | tail -n 4 | cut -d' ' -f2-
    )
fi
if [ -n "$s3cmd_logs" ]; then
    echo "$s3cmd_logs"
else
    echo "No S3 upload logs found."
fi

echo ""
echo "********* Latest S3 binary log upload logs *********"
echo ""
s3cmd_binlog_logs=""
if [ -d "$BACKUP_LOG_DIR" ]; then
    s3cmd_binlog_logs=$(
        find "$BACKUP_LOG_DIR" -maxdepth 1 -type f \
            -name 's3cmd-*-B-*' \
            -printf '%T@ %TY-%Tm-%Td %TH:%TM %s %p\n' 2> /dev/null |
            sort -n | tail -n 4 | cut -d' ' -f2-
    )
fi
if [ -n "$s3cmd_binlog_logs" ]; then
    echo "$s3cmd_binlog_logs"
else
    echo "No S3 binary log upload logs found."
fi

echo ""
echo "********* Errors in recent upload logs *********"
echo ""
if [ -f "$BACKUP_LOG_DIR/upload.log" ]; then
    grep -Ei "error|fail|denied|timeout" "$BACKUP_LOG_DIR/upload.log" | tail -20 ||
        echo "No errors found in upload.log."
else
    echo "upload.log not found."
fi

echo ""
echo "********* Running upload-related processes (s3cmd / upload) *********"
echo ""
pgrep -a -f '(s3cmd|upload)' | head -10 || echo "No upload processes currently running."
