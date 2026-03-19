#!/usr/bin/env bash

# ---
# title: "PostgreSQL Down/Uptime Check"
# description: "This script checks PostgreSQL availability by verifying uptime, service status, processes, network ports, and pg_hba configuration."
# allow_extra_args: false
# sudo: required
# ---

# Usage: ./postgresql_is_down_check.sh

set -euo pipefail

PSQL="psql"

echo "********* Server uptime *********"
uptime

echo ""
echo "********* PostgreSQL service status *********"
systemctl status postgres* --no-pager 2> /dev/null || echo "No PostgreSQL systemd service found."

echo ""
echo "********* PostgreSQL processes *********"
ps -ef | grep -E "[p]ostgres|[p]ostmaster" || echo "No PostgreSQL processes found."

echo ""
echo "********* PostgreSQL listening ports *********"
sudo ss -lntp | grep postgres 2> /dev/null || echo "Could not check PostgreSQL listening ports."

echo ""
echo "********* PostgreSQL uptime *********"
$PSQL -c "SELECT now(), pg_postmaster_start_time(), now()-pg_postmaster_start_time() AS uptime;" 2> /dev/null \
  || echo "Could not connect to PostgreSQL via psql."

echo ""
echo "********* Recent PostgreSQL log entries *********"
tail -50 /var/log/postgresql/postgresql-*.log 2> /dev/null \
    || tail -50 /var/log/postgresql/postgresql*.log 2> /dev/null \
    || echo "No PostgreSQL logs found in /var/log/postgresql/."
tail -50 $(
    $PSQL -tA -c "
        SELECT CASE
            WHEN current_setting('log_directory') LIKE '/%'
            THEN current_setting('log_directory') || '/*.log'
            ELSE current_setting('data_directory') || '/'
                 || current_setting('log_directory') || '/*.log'
        END;
    "
) 2> /dev/null \
    || echo "No PostgreSQL logs found in log_directory or problem occurred when querying for log_directory parameter."

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
