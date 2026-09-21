#!/usr/bin/env bash

# ---
# title: "PostgreSQL Down/Uptime Check"
# description: "This script checks PostgreSQL availability by verifying uptime, service status, processes, network ports, and pg_hba configuration."
# allow_extra_args: false
# sudo: always
# diagnostic_categories: []
# service_type: postgresql
# parameters:
#  - name: dbname
#    type: str
#    label: Target database
#    description: The PostgreSQL database this script connects to.
#    default: postgres
# alerts:
#   - PostgreSQLIsDown
#   - PostgreSQLUptime
# ---

# Usage: ./postgresql_is_down_check.sh

set -euo pipefail

DBNAME="${PGDATABASE:-postgres}"
if [[ ${1:-} == --dbname=* ]]; then
    DBNAME="${1#*=}"
elif [[ ${1:-} == --dbname ]]; then
    DBNAME="${2:-postgres}"
fi
export PGDATABASE="${DBNAME:-postgres}"

PSQL="psql"

echo "********* Server uptime *********"
uptime

echo ""
echo "********* PostgreSQL service status *********"
systemctl status postgres* --no-pager 2> /dev/null || echo "No PostgreSQL systemd service found."

echo ""
echo "********* PostgreSQL processes *********"
pgrep -a -f "postgres|postmaster" || echo "No PostgreSQL processes found."

echo ""
echo "********* PostgreSQL listening ports *********"
sudo ss -lntp 2> /dev/null | grep postgres || echo "Could not check PostgreSQL listening ports."

echo ""
echo "********* PostgreSQL uptime *********"
if ! pg_uptime=$($PSQL -c "SELECT now(), pg_postmaster_start_time(), now()-pg_postmaster_start_time() AS uptime;" 2>&1); then
    echo "Could not connect to PostgreSQL via psql (check --dbname): $pg_uptime"
else
    printf '%s\n' "$pg_uptime"
fi

echo ""
echo "********* Recent PostgreSQL log entries *********"
tail -50 /var/log/postgresql/postgresql-*.log 2> /dev/null ||
    tail -50 /var/log/postgresql/postgresql*.log 2> /dev/null ||
    echo "No PostgreSQL logs found in /var/log/postgresql/."
# Keep stderr out of the captured value: it is expanded as a glob, and psql
# writes warnings there on runs that otherwise succeed.
psql_err=$(mktemp)
if ! log_glob=$(
    $PSQL -tA -c "
        SELECT CASE
            WHEN current_setting('log_directory') LIKE '/%'
            THEN current_setting('log_directory') || '/*.log'
            ELSE current_setting('data_directory') || '/'
                 || current_setting('log_directory') || '/*.log'
        END;
    " 2> "$psql_err"
); then
    echo "Could not read log_directory from PostgreSQL (check --dbname): $(cat "$psql_err")"
    log_glob=""
    log_dir_known=0
else
    log_dir_known=1
fi
rm -f "$psql_err"

log_files_read=0
for f in $log_glob; do
    [ -f "$f" ] || continue
    log_files_read=1
    if ! file_tail=$(tail -50 "$f" 2>&1); then
        echo "Could not read $f: $file_tail"
    else
        printf '%s\n' "$file_tail"
    fi
done
if [ "$log_dir_known" -eq 0 ]; then
    echo "Log files were not searched, because log_directory could not be read."
elif [ "$log_files_read" -eq 0 ]; then
    echo "No PostgreSQL log files found under log_directory."
fi

echo ""
echo "********* Last logins to the server *********"
last | head -10

echo ""
echo "********* pg_hba.conf (if accessible) *********"
for hba in /etc/postgresql/*/main/pg_hba.conf /var/lib/pgsql/*/data/pg_hba.conf; do
    if [ -f "$hba" ]; then
        echo "Found: $hba"
        grep -v "^#" "$hba" | grep -v "^$"
        break
    fi
done || echo "Could not locate pg_hba.conf."

echo ""
echo "******** Reminder: check .pgpass permissions (0600) and entries to ensure that they are correct. *********"
echo ""
