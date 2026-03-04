#!/usr/bin/env bash

# ---
# title: "PostgreSQL Deadlocks Check"
# description: "This script checks for recent deadlock occurrences in PostgreSQL by searching logs."
# allow_extra_args: false
# sudo: optional
# ---

# Usage: ./postgresql_deadlocks_check.sh

set -euo pipefail

PSQL="psql"

echo "********* Recent deadlock entries in PostgreSQL logs *********"
echo ""
grep -i "deadlock" $(
    tail -50 $(
        $PSQL -tA -c "
            SELECT CASE
                WHEN current_setting('log_directory') LIKE '/%'
                THEN current_setting('log_directory') || '/*.log'
                ELSE current_setting('data_directory') || '/'
                     || current_setting('log_directory') || '/*.log'
            END;
        "
    )
) 2>/dev/null \
    || echo "No deadlock entries found in PostgreSQL logs or problem occurred when querying for log_directory parameter."
