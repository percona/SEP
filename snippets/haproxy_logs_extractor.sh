#!/usr/bin/env bash

# ---
# title: HAProxy Log Extractor
# description: This script extracts a portion of the HAProxy log based on a given time and a specified number of minutes before and after that time. Supports both ISO 8601 (rsyslog default) and BSD syslog (Mmm DD HH:MM:SS) timestamp formats.
# allow_extra_args: false
# sudo: optional
# service_type: haproxy
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
#    description: The path to your HAProxy log file
#    placeholder: /var/log/haproxy.log
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
# ---

# haproxy_logs_extractor.sh
#
# Extracts HAProxy log entries around a given timestamp.
#
# Usage: ./haproxy_logs_extractor.sh --time "<YYYY-MM-DD HH:MM:SS>" --minutes <minutes> [--log-file <path>] [--output <file|stdout>]
#
# Timestamp formats handled automatically:
#   ISO 8601  (rsyslog):      2023-10-27T15:30:00.123456+00:00 hostname haproxy[pid]: ...
#   BSD syslog (older):       Oct 27 15:30:00 hostname haproxy[pid]: ...
#
# Note: BSD syslog timestamps do not carry a year. date(1) assumes the current year,
# so log windows that cross a year boundary may not match correctly.
#
# Note on time zones: --time is interpreted in the host's local time zone, while ISO 8601
# log timestamps carry an explicit offset (e.g. +00:00). If the host is not in the same
# zone as the logs, the window will be shifted. To compare in UTC, run with TZ=UTC and
# pass --time as a UTC timestamp.
#
# Configuration:
# Default HAProxy log path if --log-file is not specified.
DEFAULT_HAPROXY_LOG="/var/log/haproxy.log"

# --- Script Functions ---

usage() {
    echo "Usage: $0 --time \"<YYYY-MM-DD HH:MM:SS>\" --minutes <minutes> [--log-file <path/to/log>] [--output <file|stdout>]"
    echo "Example: $0 --time \"2023-10-27 15:30:00\" --minutes 5 --log-file /var/log/haproxy.log --output file"
    echo "         $0 --time \"2024-01-01 10:00:00\" --minutes 30"
    echo ""
    echo "This script extracts a portion of the HAProxy log."
    echo "It will print log entries from <minutes> before to <minutes> after"
    echo "the provided timestamp."
    echo ""
    echo "Arguments:"
    echo '  --time "<YYYY-MM-DD HH:MM:SS>"   The central timestamp to focus on (required).'
    echo "  --minutes <minutes>                The number of minutes before and after the timestamp to include (required)."
    echo "  --log-file <path/to/log>           Optional. Path to the HAProxy log file. Defaults to /var/log/haproxy.log."
    echo "  --output <file|stdout>             Optional. Where to send the output. Use 'stdout' (default) or 'file'."
    exit 1
}

# --- Main Script Logic ---

TIME_ARG=""
MINUTES_ARG=""
LOG_FILE_ARG=""
OUTPUT_MODE="stdout"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --time)
            if [ -z "$2" ]; then
                echo "Error: --time requires an argument."
                usage
            fi
            TIME_ARG="$2"
            shift
            shift
            ;;
        --minutes)
            if [ -z "$2" ]; then
                echo "Error: --minutes requires an argument."
                usage
            fi
            MINUTES_ARG="$2"
            shift
            shift
            ;;
        --log-file)
            if [ -z "$2" ]; then
                echo "Error: --log-file requires an argument."
                usage
            fi
            LOG_FILE_ARG="$2"
            shift
            shift
            ;;
        --output)
            if [ -z "$2" ]; then
                echo "Error: --output requires an argument (file|stdout)."
                usage
            fi
            OUTPUT_MODE="$2"
            shift
            shift
            ;;
        -h | --help)
            usage
            ;;
        *)
            echo "Error: Unknown argument '$1'"
            usage
            ;;
    esac
done

# Validate required arguments
if [ -z "$TIME_ARG" ]; then
    echo "Error: --time argument is required."
    usage
fi

if [ -z "$MINUTES_ARG" ]; then
    echo "Error: --minutes argument is required."
    usage
fi

if ! [[ $MINUTES_ARG =~ ^[0-9]+$ ]] || [ "$MINUTES_ARG" -le 0 ]; then
    echo "Error: --minutes must be a positive integer."
    usage
fi

HAPROXY_LOG="${LOG_FILE_ARG:-$DEFAULT_HAPROXY_LOG}"
# Note: $HAPROXY_LOG is always referenced as a quoted path below; avoid over-restricting valid filenames.
if [ ! -f "$HAPROXY_LOG" ]; then
    echo "Error: HAProxy log file not found at '$HAPROXY_LOG'."
    echo "Please ensure the file exists and the path is correct."
    exit 1
fi

if [ ! -r "$HAPROXY_LOG" ]; then
    echo "Error: Cannot read HAProxy log file at '$HAPROXY_LOG'."
    echo "Please check file permissions for '$HAPROXY_LOG'."
    exit 1
fi

if ! INPUT_EPOCH=$(date -d "$TIME_ARG" +%s 2> /dev/null); then
    echo "Error: Could not parse the provided time format: \"$TIME_ARG\""
    echo 'Please ensure the time is in a valid format, e.g., "YYYY-MM-DD HH:MM:SS"'
    exit 1
fi

case "$OUTPUT_MODE" in
    stdout) ;;
    file)
        OUTPUT_FILE="haproxy_logs_${INPUT_EPOCH}.log"
        ;;
    *)
        echo "Error: --output must be 'stdout' or 'file'."
        usage
        ;;
esac

START_EPOCH=$((INPUT_EPOCH - (MINUTES_ARG * 60)))
END_EPOCH=$((INPUT_EPOCH + (MINUTES_ARG * 60)))

# Filter the log file using awk.
#
# HAProxy syslog lines start with one of two timestamp formats:
#   ISO 8601 / RFC3339: first field, e.g. "2023-10-27T15:30:00.123456+00:00"
#   BSD syslog:          first 15 chars, e.g. "Oct 27 15:30:00"
#
# We try ISO first; if date(1) cannot parse it we fall back to BSD.
# Lines with no recognisable timestamp (continuation / stack-trace lines)
# leave log_epoch unchanged (0), so they do not alter print_flag.
# They are printed when print_flag is already set, preserving multi-line entries.

_filter_log() {
    awk -v start_e="$START_EPOCH" -v end_e="$END_EPOCH" '
BEGIN {
    print_flag = 0;
}
{
    log_epoch = 0;

    # Try ISO 8601 / RFC3339 (first field, may include fractional seconds + timezone)
    ts = "";
    if ($1 ~ /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}/) {
        ts = $1;
    } else if (substr($0, 1, 15) ~ /^[A-Z][a-z]{2} [ 0-9][0-9] [0-9]{2}:[0-9]{2}:[0-9]{2}/) {
        ts = substr($0, 1, 15);
    }

    if (ts != "") {
        cmd = "date -d \"" ts "\" +%s 2>/dev/null";
        cmd | getline log_epoch;
        close(cmd);
    }

    if (log_epoch != "" && log_epoch != 0) {
        if (log_epoch >= start_e && log_epoch <= end_e) {
            print_flag = 1;
        } else if (log_epoch > end_e && print_flag == 1) {
            exit;
        } else if (log_epoch < start_e) {
            print_flag = 0;
        }
    }
}
{
    if (print_flag == 1) {
        print;
    }
}' "$HAPROXY_LOG"
}

if [[ $OUTPUT_MODE == "file" ]]; then
    _filter_log > "$OUTPUT_FILE"
    echo "Output written to $OUTPUT_FILE"
else
    _filter_log
fi
