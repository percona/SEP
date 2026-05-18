#!/usr/bin/env bash

# ---
# title: MongoDB Log Extractor
# description: This script extracts a portion of the MongoDB log containing the time of the original crash and any restart attempts.
# allow_extra_args: false
# sudo: always
# service_type: mongodb
# parameters:
#  - name: time
#    type: str
#    label: Issue Time
#    description: The central timestamp to focus on (e.g., "2023-10-27 15:30:00").
#    required: true
#  - name: minutes
#    type: int
#    label: Minutes
#    description: The number of minutes before and after to include.
#    ge: 1
#    required: true
#  - name: log-file
#    type: str
#    label: Log file path
#    description: The path to your MongoDB log file.
#    placeholder: /var/log/mongodb/mongod.log
#  - name: output
#    type: str
#    description: Where to send the output
#    label: Output destination
#    default: stdout
#    choices:
#      - value: stdout
#        label: Print to the terminal (default)
#      - value: file
#        label: Write the output to a file named by the timestamp
# alerts:
#   - MongoDBInstanceNotAvailable
# ---

set -euo pipefail

DEFAULT_MONGODB_LOG="/var/log/mongodb/mongod.log"

TIME_ARG=""
MINUTES_ARG=""
LOG_FILE_ARG=""
OUTPUT_MODE="stdout"

usage() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: $(basename "$0") --time "<YYYY-MM-DD HH:MM:SS>" --minutes <N> [OPTIONS]

Extract MongoDB log entries around a given timestamp.

Options:
  --time "<YYYY-MM-DD HH:MM:SS>"  Central timestamp (required).
  --minutes N                      Minutes before/after to include (required).
  --log-file <path>                MongoDB log file (default: $DEFAULT_MONGODB_LOG).
  --output <stdout|file>           Output destination (default: stdout).
  -h, --help                       Show this help message.
EOS
    exit "${exit_code}"
}

if ! OPTS=$(getopt --options h --longoptions 'time:,minutes:,log-file:,output:,help' -- "$@"); then
    echo "Error parsing options" >&2
    usage 1
fi

eval set -- "$OPTS"

while [[ -n $* ]]; do
    case "$1" in
        --time)
            TIME_ARG="$2"
            shift 2
            ;;
        --minutes)
            MINUTES_ARG="$2"
            shift 2
            ;;
        --log-file)
            LOG_FILE_ARG="$2"
            shift 2
            ;;
        --output)
            OUTPUT_MODE="$2"
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

if [[ -z $TIME_ARG ]]; then
    echo "Error: --time is required." >&2
    usage 1
fi

if [[ -z $MINUTES_ARG ]]; then
    echo "Error: --minutes is required." >&2
    usage 1
fi

if ! [[ $MINUTES_ARG =~ ^[0-9]+$ ]] || [[ $MINUTES_ARG -le 0 ]]; then
    echo "Error: --minutes must be a positive integer." >&2
    usage 1
fi

if [[ -z $LOG_FILE_ARG ]]; then
    # Auto-detect log path from mongod config, same discovery chain as mongodb_ftdc_collect.sh
    MONGOD_CMD=""
    MONGOD_PID=$(pgrep -x mongod 2> /dev/null | head -1)
    if [[ -n $MONGOD_PID ]]; then
        MONGOD_CMD=$(ps -p "$MONGOD_PID" -o args= 2> /dev/null || true)
    fi
    CONFIG_FILE=""
    if [[ -n $MONGOD_CMD ]]; then
        if [[ $MONGOD_CMD =~ --config[[:space:]]+([^[:space:]]+) ]]; then
            CONFIG_FILE="${BASH_REMATCH[1]}"
        elif [[ $MONGOD_CMD =~ -f[[:space:]]+([^[:space:]]+) ]]; then
            CONFIG_FILE="${BASH_REMATCH[1]}"
        elif [[ $MONGOD_CMD =~ --config=([^[:space:]]+) ]]; then
            CONFIG_FILE="${BASH_REMATCH[1]}"
        fi
    fi
    if [[ -z $CONFIG_FILE ]]; then
        for conf in /etc/mongod.conf /etc/mongodb.conf /usr/local/etc/mongod.conf; do
            if [[ -f $conf ]]; then
                CONFIG_FILE="$conf"
                break
            fi
        done
    fi
    if [[ -n $CONFIG_FILE && -f $CONFIG_FILE ]]; then
        DETECTED_LOG=$(grep -E '^\s*path\s*:' "$CONFIG_FILE" 2> /dev/null | head -1 | sed 's/.*path[[:space:]]*:[[:space:]]*//' | tr -d "\"'" | xargs 2> /dev/null || true)
        if [[ -n $DETECTED_LOG ]]; then
            LOG_FILE_ARG="$DETECTED_LOG"
            echo "Detected log file from config ($CONFIG_FILE): $LOG_FILE_ARG" >&2
        fi
    fi
fi

MONGODB_LOG="${LOG_FILE_ARG:-$DEFAULT_MONGODB_LOG}"

if [[ ! -f $MONGODB_LOG ]]; then
    echo "Error: MongoDB log file not found at '$MONGODB_LOG'." >&2
    exit 1
fi

if [[ ! -r $MONGODB_LOG ]]; then
    echo "Error: Cannot read MongoDB log file at '$MONGODB_LOG'." >&2
    exit 1
fi

if ! INPUT_EPOCH=$(date -d "$TIME_ARG" +%s 2> /dev/null); then
    echo "Error: Could not parse time: \"$TIME_ARG\"" >&2
    exit 1
fi

START_EPOCH=$((INPUT_EPOCH - (MINUTES_ARG * 60)))
END_EPOCH=$((INPUT_EPOCH + (MINUTES_ARG * 60)))

# Both legacy text (pre-4.4) and JSON structured (4.4+) logs embed the ISO 8601
# timestamp as a 19-character substring; the awk regex matches both formats.
filter_log() {
    awk -v start_e="$START_EPOCH" -v end_e="$END_EPOCH" '
BEGIN { print_flag = 0 }
{
    log_timestamp_str = ""
    if (match($0, /[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]/)) {
        log_timestamp_str = substr($0, RSTART, 19)
    }
    if (log_timestamp_str != "") {
        cmd = "date -d \"" log_timestamp_str "\" +%s 2>/dev/null"
        cmd | getline log_epoch
        close(cmd)
        if (log_epoch >= start_e && log_epoch <= end_e) {
            print_flag = 1
        } else if (log_epoch > end_e && print_flag == 1) {
            exit
        }
    }
    if (print_flag == 1) print
}' "$MONGODB_LOG"
}

if [[ $OUTPUT_MODE == "file" ]]; then
    OUTPUT_FILE="mongodb_log_${INPUT_EPOCH}.log"
    filter_log > "$OUTPUT_FILE"
    echo "Output written to $OUTPUT_FILE"
else
    filter_log
fi
