#!/usr/bin/env bash

# This script executes the 'dmesg -T' command with sudo.
# 'dmesg' displays the kernel ring buffer messages.
# The '-T' option adds a human-readable timestamp to each message.

sudo dmesg -T
