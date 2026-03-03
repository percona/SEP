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
echo ""
uptime

echo "********* PostgreSQL service status *********"
echo ""
systemctl status postgres* --no-pager 2> /dev/null || echo "No PostgreSQL systemd service found."

echo ""
echo "********* PostgreSQL processes *********"
echo ""
ps -ef | grep "[p]ostgres" || echo "No PostgreSQL processes found."

echo ""
echo "********* PostgreSQL listening ports *********"
echo ""
sudo ss -lntp | grep postgres 2> /dev/null || echo "Could not check PostgreSQL listening ports."

echo ""
echo "********* PostgreSQL uptime *********"
echo ""
echo ""
$PSQL -c "SELECT now(), pg_postmaster_start_time(), now()-pg_postmaster_start_time() AS uptime;" 2> /dev/null \
  || echo "Could not connect to PostgreSQL via psql."

echo ""
echo "********* Recent PostgreSQL log entries *********"
echo ""
tail -50 /var/log/postgresql/postgresql-*.log 2> /dev/null \
    || tail -50 /var/log/postgresql/postgresql*.log 2> /dev/null \
    || echo "No PostgreSQL logs found in /var/log/postgresql/."

echo ""
echo "********* Last logins to the server *********"
echo ""
last | head -10

echo ""
echo "********* pg_hba.conf (if accessible) *********"
echo ""
for hba in /etc/postgresql/*/main/pg_hba.conf /var/lib/pgsql/*/data/pg_hba.conf; do
    if [ -f "$hba" ]; then
        echo "Found: $hba"
        grep -v "^#" "$hba" | grep -v "^$"
        break
    fi
done || echo "Could not locate pg_hba.conf."

echo ""
echo "******** Reminder: check `.pgpass` permissions (0600) and entries to ensure that they are correct. *********"
echo ""
