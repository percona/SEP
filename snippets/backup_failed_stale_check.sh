#!/usr/bin/env bash

# ---
# title: "(Stale) Backup Failed Check"
# description: "This script checks mydumper/xtrabackup logs, retention configuration, and disk space to diagnose failed and/or stale backups, including binary log backups."
# allow_extra_args: false
# sudo: optional
# service_type: mysql
# alerts:
#   - BackupFailed
#   - StaleBackup
#   - StaleBackupLog
# ---

# Usage: ./backup_failed_stale_check.sh

set -euo pipefail

BACKUP_LOG_DIR="/var/log/percona/backups"
BACKUP_CONFIG="/home/percona/.config/percona/backup/backup_config.yml"

echo "********* Recent mydumper backup log *********"
echo ""
if [ -f "$BACKUP_LOG_DIR/mydumper.log" ]; then
    tail -n 20 "$BACKUP_LOG_DIR/mydumper.log"
else
    echo "mydumper.log not found."
fi

echo ""
echo "********* Recent xtrabackup backup log *********"
echo ""
if [ -f "$BACKUP_LOG_DIR/xtrabackup.log" ]; then
    tail -n 20 "$BACKUP_LOG_DIR/xtrabackup.log"
else
    echo "xtrabackup.log not found."
fi

echo ""
echo "********* Latest detailed backup logs *********"
echo ""
detailed_logs=""
if [ -d "$BACKUP_LOG_DIR" ]; then
    detailed_logs=$(
        find "$BACKUP_LOG_DIR" -maxdepth 1 -type f \
            \( -name 'xtrabackup-*' -o -name 'mydumper-*' \) \
            -printf '%T@ %TY-%Tm-%Td %TH:%TM %s %p\n' 2> /dev/null |
            sort -n | tail -n 4 | cut -d' ' -f2-
    )
fi
if [ -n "$detailed_logs" ]; then
    echo "$detailed_logs"
else
    echo "No detailed backup logs found."
fi

echo ""
echo "********* Running backup processes *********"
echo ""
ps aux | head -n1
pgrep -a -f '(xtrabackup|mydumper)' || echo "No backup processes currently running."

echo ""
echo "********* Backup retention configuration *********"
echo ""
if [ -f "$BACKUP_CONFIG" ]; then
    grep -E "BINLOG_PURGE_DAYS|MYDUMPER_DAILY_PURGE|MYDUMPER_WEEKLY_PURGE|XTRABACKUP_COPIES" "$BACKUP_CONFIG" ||
        echo "No retention settings found in config." || true
else
    echo "Backup config not found at $BACKUP_CONFIG"
fi

echo ""
echo "********* Backup directory sizes *********"
echo ""
if [ -f "$BACKUP_CONFIG" ]; then
    BACKUP_DIR=$(grep BACKUP_DIR "$BACKUP_CONFIG" 2> /dev/null | cut -d ":" -f2 | xargs || true)
    if [ -n "${BACKUP_DIR:-}" ] && [ -d "$BACKUP_DIR" ]; then
        du -hd1 "$BACKUP_DIR" 2> /dev/null | tail -10
    else
        echo "Backup directory not found."
    fi
else
    echo "Backup config not found."
fi

echo ""
echo "********* Recent binlog puller logs *********"
echo ""
binlog_puller_logs=""
if [ -d "$BACKUP_LOG_DIR" ]; then
    binlog_puller_logs=$(
        find "$BACKUP_LOG_DIR" -maxdepth 1 -type f \
            -name 'binlog_puller*' \
            -printf '%T@ %TY-%Tm-%Td %TH:%TM %s %p\n' 2> /dev/null |
            sort -n | tail -n 4 | cut -d' ' -f2-
    )
fi
if [ -n "$binlog_puller_logs" ]; then
    echo "$binlog_puller_logs"
else
    echo "No binlog puller logs found."
fi

for logfile in "$BACKUP_LOG_DIR"/binlog_puller_*.log; do
    if [ -f "$logfile" ]; then
        echo ""
        echo "--- $(basename "$logfile") (last 20 lines) ---"
        tail -n 20 "$logfile"
    fi
done

echo ""
echo "********* Running mysqlbinlog processes *********"
echo ""
pgrep -a -f mysqlbinlog || echo "No mysqlbinlog processes currently running."

echo ""
echo "********* Backup cron jobs *********"
echo ""
if [ -f /etc/cron.d/percona_crons ]; then
    cat /etc/cron.d/percona_crons
else
    echo "percona_crons not found in /etc/cron.d/"
fi

echo ""
echo "********* Disk space *********"
echo ""
df -hP
