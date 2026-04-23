#!/usr/bin/env bash

# ---
# title: MHA Config File Discovery Script
# description: This script finds all MHA (Master High Availability) config files, including those referenced by !include and !includedir directives.
# allow_extra_args: false
# sudo: optional
# service_type: mysql
# parameters: []
# ---

set -e

# Track processed files to avoid infinite loops
declare -A PROCESSED_FILES

process_config_file() {
    local file="$1"
    # Avoid re-processing
    if [[ -n ${PROCESSED_FILES["$file"]} ]]; then
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
            [[ $line =~ ^#.*$ ]] && continue
            if [[ $line =~ ^!include[[:space:]]+(.+) ]]; then
                included_file="${BASH_REMATCH[1]}"
                # Expand ~ and variables
                included_file=$(eval echo "$included_file")
                process_config_file "$included_file"
            elif [[ $line =~ ^!includedir[[:space:]]+(.+) ]]; then
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

echo "=== MHA Config File Discovery Script ==="
echo

# List of common MHA config file locations
COMMON_PATHS=(
    "/etc/mha/app1.cnf"
    "/etc/mha/app1.conf"
    "/etc/masterha/app1.cnf"
    "/etc/masterha/app1.conf"
    "/etc/mha/mha.conf"
    "/etc/masterha/mha.conf"
    "/etc/mha.cnf"
    "/etc/mha.conf"
    "/etc/masterha.cnf"
    "/etc/masterha.conf"
)

# Get config files from MHA directories (if available)
echo "Checking common MHA config directories..."
MHA_DIRS=(
    "/etc/mha"
    "/etc/masterha"
    "/usr/local/etc/mha"
    "/usr/local/etc/masterha"
)

for mha_dir in "${MHA_DIRS[@]}"; do
    if [ -d "$mha_dir" ]; then
        for conf_file in "$mha_dir"/*.cnf "$mha_dir"/*.conf; do
            [ -e "$conf_file" ] && COMMON_PATHS+=("$conf_file")
        done
    fi
done

# Remove duplicates
readarray -t UNIQUE_PATHS < <(printf "%s\n" "${COMMON_PATHS[@]}" | sort -u)

# Print found config files and their included files/contents
echo "=== Checking common MHA config file locations (and their includes) ==="
for path in "${UNIQUE_PATHS[@]}"; do
    process_config_file "$path"
done

echo
echo "=== Done ==="
