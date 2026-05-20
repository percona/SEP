#!/usr/bin/env bash

# ---
# title: MongoDB FTDC Collect
# description: Locates the MongoDB Full-Time Diagnostic Data Capture (FTDC) directory, lists its files, and optionally copies them to a destination for offline analysis.
# allow_extra_args: false
# sudo: always
# service_type: mongodb
# parameters:
#  - name: dest
#    type: str
#    label: Destination directory
#    description: Directory where FTDC files are copied for offline analysis. Defaults to /tmp/mongodb-ftdc.
#    default: /tmp/mongodb-ftdc
#    pattern: ^/[A-Za-z0-9._/-]+$
#  - name: data-dir
#    type: str
#    label: MongoDB data directory
#    description: Path to the MongoDB data directory containing diagnostic.data/. Auto-detected if not specified.
#    placeholder: /var/lib/mongodb
# alerts:
#   - MongoDBInstanceNotAvailable
# ---

# mongodb_ftdc_collect.sh
#
# Locates the MongoDB FTDC directory (diagnostic.data/) and collects its files.
# FTDC files are binary BSON documents that record server metrics at 1-second
# granularity and are invaluable for post-mortem analysis of crashes and slowdowns.
#
# Auto-detection order for the MongoDB data directory:
#   1. --data-dir argument (if provided)
#   2. --dbpath flag from the running mongod process
#   3. storage.dbPath from /etc/mongod.conf
#   4. Common default paths (/var/lib/mongodb, /data/db, /var/lib/mongo)
#
# Usage: ./mongodb_ftdc_collect.sh [--dest <dir>] [--data-dir <dir>]

set -euo pipefail

DEST="/tmp/mongodb-ftdc"
DATA_DIR=""

usage() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: $(basename "$0") [OPTIONS]

Locate and collect MongoDB FTDC (Full-Time Diagnostic Data Capture) files.

Options:
  --dest <dir>       Destination directory for copied FTDC files (default: /tmp/mongodb-ftdc).
                     Pass an empty string to only list files without copying.
  --data-dir <dir>   MongoDB data directory containing diagnostic.data/.
                     Auto-detected from the running process or config if not specified.
  -h, --help         Show this help message.
EOS
    exit "${exit_code}"
}

if ! OPTS=$(getopt --options h --longoptions 'dest:,data-dir:,help' -- "$@"); then
    echo "Error parsing options" >&2
    usage 1
fi

eval set -- "$OPTS"

while [[ -n $* ]]; do
    case "$1" in
        --dest)
            DEST="$2"
            shift 2
            ;;
        --data-dir)
            DATA_DIR="$2"
            shift 2
            ;;
        -h | --help) usage ;;
        --)
            shift
            break
            ;;
        *)
            echo "Unrecognized option '$1'" >&2
            usage 1
            ;;
    esac
done

echo "=== MongoDB FTDC Collect ==="
echo ""

if [[ -n $DATA_DIR ]]; then
    echo "Using provided data directory: $DATA_DIR"
else
    # Try to detect --dbpath from the running mongod process
    MONGOD_CMD=""
    MONGOD_PID=$(pgrep -x mongod 2> /dev/null | head -1)
    if [[ -n $MONGOD_PID ]]; then
        MONGOD_CMD=$(ps -p "$MONGOD_PID" -o args= 2> /dev/null || true)
    fi
    if [[ -n $MONGOD_CMD ]]; then
        if [[ $MONGOD_CMD =~ --dbpath[[:space:]]+([^[:space:]]+) ]]; then
            DATA_DIR="${BASH_REMATCH[1]}"
            echo "Detected data directory from running process: $DATA_DIR"
        elif [[ $MONGOD_CMD =~ --dbpath=([^[:space:]]+) ]]; then
            DATA_DIR="${BASH_REMATCH[1]}"
            echo "Detected data directory from running process: $DATA_DIR"
        fi
    fi

    # Try to read storage.dbPath from the config file
    if [[ -z $DATA_DIR ]]; then
        for conf in /etc/mongod.conf /etc/mongodb.conf /usr/local/etc/mongod.conf; do
            if [[ -f $conf ]]; then
                DB_PATH=$(awk '
                    /^[[:space:]]*storage[[:space:]]*:[[:space:]]*$/ { in_section = 1; next }
                    in_section && /^[^[:space:]#]/ { in_section = 0 }
                    in_section && /^[[:space:]]+dbPath[[:space:]]*:/ {
                        sub(/^[[:space:]]*dbPath[[:space:]]*:[[:space:]]*/, "")
                        print
                        exit
                    }
                ' "$conf" 2> /dev/null | tr -d "\"'" | xargs 2> /dev/null || true)
                if [[ -n $DB_PATH ]]; then
                    DATA_DIR="$DB_PATH"
                    echo "Detected data directory from config ($conf): $DATA_DIR"
                    break
                fi
            fi
        done
    fi

    # Fall back to common default paths
    if [[ -z $DATA_DIR ]]; then
        for candidate in /var/lib/mongodb /data/db /var/lib/mongo; do
            if [[ -d $candidate ]]; then
                DATA_DIR="$candidate"
                echo "Using default data directory: $DATA_DIR"
                break
            fi
        done
    fi
fi

if [[ -z $DATA_DIR ]]; then
    echo "Error: Could not locate the MongoDB data directory."
    echo "Please specify it explicitly with --data-dir."
    exit 1
fi

if [[ ! -d $DATA_DIR ]]; then
    echo "Error: Data directory '$DATA_DIR' does not exist."
    exit 1
fi

FTDC_DIR="$DATA_DIR/diagnostic.data"

if [[ ! -d $FTDC_DIR ]]; then
    echo "Error: FTDC directory not found at '$FTDC_DIR'."
    echo "Ensure MongoDB is or was running with FTDC enabled (enabled by default since v3.2)."
    exit 1
fi

echo ""
echo "=== FTDC directory: $FTDC_DIR ==="
echo ""

FTDC_FILES=$(find "$FTDC_DIR" -maxdepth 1 -type f | sort)

if [[ -z $FTDC_FILES ]]; then
    echo "No FTDC files found in '$FTDC_DIR'."
    exit 0
fi

echo "Files:"
ls -lh "$FTDC_DIR"
echo ""

TOTAL_SIZE=$(du -sh "$FTDC_DIR" | cut -f1)
FILE_COUNT=$(find "$FTDC_DIR" -maxdepth 1 -type f | wc -l)
echo "Total: $FILE_COUNT file(s), $TOTAL_SIZE"
echo ""

if [[ -z $DEST ]]; then
    echo "No destination specified (--dest). Files listed above but not copied."
    echo "=== Done ==="
    exit 0
fi

echo "=== Copying FTDC files to $DEST ==="
mkdir -p "$DEST"

mapfile -d '' METRICS_FILES < <(find "$FTDC_DIR" -maxdepth 1 -type f -name 'metrics.*' -print0)
if [[ ${#METRICS_FILES[@]} -eq 0 ]]; then
    COPIED=0
    echo "No metrics files found to copy."
else
    cp -v -- "${METRICS_FILES[@]}" "$DEST/"
    COPIED=${#METRICS_FILES[@]}
fi

echo ""
echo "Copied $COPIED file(s) to $DEST."
echo ""
echo "To decode FTDC files offline, use one of:"
echo "  - keyhole: keyhole --diag $DEST"
echo "  - bsondump: bsondump <file>"
echo ""
echo "=== Done ==="
