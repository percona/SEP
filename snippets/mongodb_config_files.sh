#!/usr/bin/env bash

# ---
# title: MongoDB Config File Discovery Script
# description: This script finds and displays the MongoDB configuration file, including detection from the running process command line.
# allow_extra_args: false
# sudo: optional
# service_type: mongodb
# parameters: []
# alerts:
#   - MongoDBInstanceNotAvailable
#   - MongoDBReplicaState
#   - MongoDBNoPrimary
# ---

set -e

print_config_file() {
    local file="$1"
    if [ -f "$file" ]; then
        echo
        echo "---- Found: $file ----"
        ls -l "$file"
        echo
        cat "$file"
        echo "----------------------"
        return 0
    fi
    return 1
}

echo "=== MongoDB Config File Discovery Script ==="
echo

# Try to detect the config file from the running mongod process command line
echo "Checking running mongod process for --config flag..."
PROCESS_CONFIG=""
MONGOD_CMD=$(ps -wweo args 2> /dev/null | grep -E '^\s*(sudo\s+)?mongod' | grep -v grep | head -1 || true)
if [[ -n $MONGOD_CMD ]]; then
    # Extract --config or -f argument value
    if [[ $MONGOD_CMD =~ --config[[:space:]]+([^[:space:]]+) ]]; then
        PROCESS_CONFIG="${BASH_REMATCH[1]}"
    elif [[ $MONGOD_CMD =~ -f[[:space:]]+([^[:space:]]+) ]]; then
        PROCESS_CONFIG="${BASH_REMATCH[1]}"
    elif [[ $MONGOD_CMD =~ --config=([^[:space:]]+) ]]; then
        PROCESS_CONFIG="${BASH_REMATCH[1]}"
    fi
fi

FOUND=0

if [[ -n $PROCESS_CONFIG ]]; then
    echo "Detected config file from running process: $PROCESS_CONFIG"
    if print_config_file "$PROCESS_CONFIG"; then
        FOUND=1
    fi
fi

# Check common MongoDB config file locations
COMMON_PATHS=(
    "/etc/mongod.conf"
    "/etc/mongodb.conf"
    "/usr/local/etc/mongod.conf"
    "/opt/homebrew/etc/mongod.conf"
    "/etc/mongos.conf"
)

echo "=== Checking common MongoDB config file locations ==="
for path in "${COMMON_PATHS[@]}"; do
    if [[ $path != "$PROCESS_CONFIG" ]]; then
        if print_config_file "$path"; then
            FOUND=1
        fi
    fi
done

if [[ $FOUND -eq 0 ]]; then
    echo "No MongoDB configuration file found in common locations."
    echo "You can specify the config path explicitly via --config when starting mongod."
fi

echo
echo "=== Done ==="
