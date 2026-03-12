#!/usr/bin/env bash

# ---
# title: "MySQL Auto Increment Exhaustion Check"
# description: "This script checks auto-increment column usage ratios across all tables to identify columns approaching their datatype limits."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to defaults-file
#    description: Path to defaults-file
# ---

# Usage: ./mysql_auto_increment_exhaustion_check.sh [--defaults-file=path]

set -euo pipefail

DEFAULTS_FILE=""
if [[ "${1:-}" == --defaults-file=* ]]; then
    DEFAULTS_FILE="$1"
    shift
elif [[ "${1:-}" == --defaults-file ]]; then
    DEFAULTS_FILE="--defaults-file=${2}"
    shift 2
fi

MYSQL="mysql $DEFAULTS_FILE -B"

echo "********* Auto-increment usage by table (sorted by ratio) *********"
$MYSQL -e "
SELECT
    TABLE_SCHEMA AS db_name,
    TABLE_NAME AS table_name,
    COLUMN_NAME AS column_name,
    DATA_TYPE AS data_type,
    COLUMN_TYPE AS column_type,
    IF(LOCATE('unsigned', COLUMN_TYPE) > 0, 1, 0) AS is_unsigned,
    (CASE DATA_TYPE
        WHEN 'tinyint' THEN 255
        WHEN 'smallint' THEN 65535
        WHEN 'mediumint' THEN 16777215
        WHEN 'int' THEN 4294967295
        WHEN 'bigint' THEN 18446744073709551615
    END >> IF(LOCATE('unsigned', COLUMN_TYPE) > 0, 0, 1)) AS max_value,
    AUTO_INCREMENT AS auto_increment,
    ROUND(AUTO_INCREMENT / (CASE DATA_TYPE
        WHEN 'tinyint' THEN 255
        WHEN 'smallint' THEN 65535
        WHEN 'mediumint' THEN 16777215
        WHEN 'int' THEN 4294967295
        WHEN 'bigint' THEN 18446744073709551615
    END >> IF(LOCATE('unsigned', COLUMN_TYPE) > 0, 0, 1)) * 100, 2) AS ratio
FROM INFORMATION_SCHEMA.COLUMNS
INNER JOIN INFORMATION_SCHEMA.TABLES USING (TABLE_SCHEMA, TABLE_NAME)
WHERE TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND EXTRA = 'auto_increment'
ORDER BY ratio DESC;
"
