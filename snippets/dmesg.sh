#!/usr/bin/env bash

# ---
# allow_extra_args: false
# atw:
#  - SERVER_CRASHED_RESTART_SUCCESSFUL
#  - SERVER_CRASHED_RESTART_NOT_SUCCESSFUL
#  - NOT_RESPONDING
#  - TEMPORARY_STALLS
# ---

# This script executes the 'dmesg -T' command with sudo.
# 'dmesg' displays the kernel ring buffer messages.
# The '-T' option adds a human-readable timestamp to each message.

sudo dmesg -T
