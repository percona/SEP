#!/usr/bin/env bash

# ---
# title: "PMM Agent Service Status Check"
# description: "This script checks the status of (user/system-level) pmm-agent service, and gathers relevant logs for troubleshooting."
# allow_extra_args: false
# sudo: always
# service_type: generic
# alerts:
#   - PostgreSQLExporterError
# ---

set -euo pipefail

echo "********* PMM Agent process check *********"
if pgrep -af pmm-agent; then
    echo ""
    echo "pmm-agent process is currently running."
else
    echo "WARNING: No pmm-agent process found running on this system."
fi

echo ""
echo "********* System-level pmm-agent service *********"
if systemctl cat pmm-agent.service &> /dev/null; then
    echo "pmm-agent is configured as a system-level systemd service."
    echo ""
    systemctl status pmm-agent.service --no-pager 2>&1 || true
    echo ""
    echo "********* Recent journal logs (system-level) *********"
    journalctl -u pmm-agent.service --no-pager -n 50 2>&1 || true
else
    echo "pmm-agent is NOT configured as a system-level systemd service."
fi

echo ""
echo "********* User-level pmm-agent service *********"
found_user_service=false

for user_dir in /home/*/; do
    username="$(basename "$user_dir")"
    uid="$(id -u "$username" 2> /dev/null)" || continue
    runtime_dir="/run/user/${uid}"

    [[ -d $runtime_dir ]] || continue

    if sudo -u "$username" XDG_RUNTIME_DIR="$runtime_dir" systemctl --user cat pmm-agent.service &> /dev/null; then
        found_user_service=true
        echo "********* Found user-level pmm-agent service for user: ${username} (UID: ${uid}) *********"
        echo ""
        sudo -u "$username" XDG_RUNTIME_DIR="$runtime_dir" systemctl --user status pmm-agent.service --no-pager 2>&1 || true
        echo ""
        echo "********* Recent journal logs (user-level, user: ${username}) *********"
        sudo -u "$username" XDG_RUNTIME_DIR="$runtime_dir" journalctl --user -u pmm-agent.service --no-pager -n 50 2>&1 ||
            journalctl _UID="$uid" -u pmm-agent --no-pager -n 50 2>&1 || true
    fi
done

if [[ $found_user_service == "false" ]]; then
    echo "No user-level pmm-agent systemd service found for any user in /home."
fi
