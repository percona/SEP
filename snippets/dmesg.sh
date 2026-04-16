#!/usr/bin/env bash

# ---
# allow_extra_args: false
# sudo: true
# atw:
#  - SERVER_CRASHED_RESTART_SUCCESSFUL
#  - SERVER_CRASHED_RESTART_NOT_SUCCESSFUL
#  - NOT_RESPONDING
#  - TEMPORARY_STALLS
# service_type: generic
# alerts:
#   - MySQLInstanceNotAvailable
#   - PostgreSQLIsDown
#   - HighMemoryUsage
#   - HighIOUtilization
# ---

# This script executes the 'dmesg -T' command with sudo.
# 'dmesg' displays the kernel ring buffer messages.
# The '-T' option adds a human-readable timestamp to each message.

dmesg -T
