#!/usr/bin/env bash

# ---
# title: MySQL Config File Discovery Script
# description: This script finds all MySQL config files, including those referenced by !include and !includedir directives.
# allow_extra_args: false
# parameters: []
# atw:
#  - SERVER_CRASHED_RESTART_NOT_SUCCESSFUL
# ---


set -e

# Track processed files to avoid infinite loops
declare -A PROCESSED_FILES

process_config_file() {
  local file="$1"
  # Avoid re-processing
  if [[ -n "${PROCESSED_FILES["$file"]}" ]]; then
    return
  fi
  PROCESSED_FILES["$file"]=1

  if [ -f "$file" ]; then
    echo
    echo "---- Found: $file ----"
    ls -l "$file"
    echo
    cat "$file"
    echo "----------------------"
    # Parse for !include and !includedir
    while IFS= read -r line; do
      # Remove leading/trailing whitespace
      line="$(echo "$line" | sed 's/^ *//;s/ *$//')"
      # Skip comments
      [[ "$line" =~ ^#.*$ ]] && continue
      if [[ "$line" =~ ^!include[[:space:]]+(.+) ]]; then
        included_file="${BASH_REMATCH[1]}"
        # Expand ~ and variables
        included_file=$(eval echo "$included_file")
        process_config_file "$included_file"
      elif [[ "$line" =~ ^!includedir[[:space:]]+(.+) ]]; then
        included_dir="${BASH_REMATCH[1]}"
        included_dir=$(eval echo "$included_dir")
        if [ -d "$included_dir" ]; then
          for incf in "$included_dir"/*.cnf; do
            [ -e "$incf" ] && process_config_file "$incf"
          done
        fi
      fi
    done < "$file"
  fi
}

echo "=== MySQL Config File Discovery Script ==="
echo

# List of common MySQL config file locations
COMMON_PATHS=(
  "/etc/my.cnf"
  "/etc/mysql/my.cnf"
  "/usr/local/etc/my.cnf"
  "$HOME/.my.cnf"
  "/etc/mysql/mysql.conf.d/mysqld.cnf"
  "/etc/mysql/conf.d/mysql.cnf"
  "/usr/etc/my.cnf"
  "/opt/local/etc/mysql56/my.cnf"
  "/opt/local/etc/mysql57/my.cnf"
  "/opt/local/etc/mysql/my.cnf"
)

# Get config files from mysqld --help --verbose (if available)
echo "Checking mysqld for config file locations..."
MYSQLD_PATH=$(command -v mysqld)
if [ -n "$MYSQLD_PATH" ]; then
  mysqld --help --verbose 2>/dev/null | grep -A 1 "Default options are read from the following files in the given order:" | tail -n 1 | tr -s ' ' | tr ' ' '\n' | grep -E '\.cnf$' > /tmp/mysql_config_files.txt
  while read -r line; do
    [ -n "$line" ] && COMMON_PATHS+=("$line")
  done < /tmp/mysql_config_files.txt
  rm -f /tmp/mysql_config_files.txt
fi

# Remove duplicates
UNIQUE_PATHS=($(printf "%s\n" "${COMMON_PATHS[@]}" | sort -u))

# Print found config files and their included files/contents
echo "=== Checking common config file locations (and their includes) ==="
for path in "${UNIQUE_PATHS[@]}"; do
  process_config_file "$path"
done

echo
echo "=== Done ==="
