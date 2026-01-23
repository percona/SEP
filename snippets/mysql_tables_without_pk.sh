#!/usr/bin/env bash

# ---
# title: "Tables without Primary Key"
# description: "Prints all tables in all databases that do not have a primary key."
# allow_extra_args: true
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# atw:
#  - NATIVE_ASYNC_REPLICATION
# ---

# Usage: ./mysql_tables_without_pk.sh [--defaults-file=path] [mysql_args...]
# Example: ./mysql_tables_without_pk.sh --defaults-file=/etc/mysql/my.cnf -uroot -p

# Check for --defaults-file argument
DEFAULTS_FILE=""
if [[ $1 == --defaults-file=* ]]; then
    DEFAULTS_FILE="$1"
    shift
fi

MYSQL="mysql $DEFAULTS_FILE -B"

# Replace the above with a heredoc for better multiline handling
$MYSQL <<EOF
SELECT
  TABLES.table_name, TABLES.TABLE_SCHEMA
FROM INFORMATION_SCHEMA.TABLES
LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS c
  ON (
    INFORMATION_SCHEMA.TABLES.TABLE_NAME = c.TABLE_NAME
    AND c.CONSTRAINT_SCHEMA = INFORMATION_SCHEMA.TABLES.TABLE_SCHEMA
    AND c.constraint_name = 'PRIMARY'
  )
WHERE
  INFORMATION_SCHEMA.TABLES.table_schema NOT IN ('information_schema','performance_schema','mysql','sys')
  AND c.constraint_name IS NULL
EOF
