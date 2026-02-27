#!/usr/bin/env bash

# ---
# title: ProxySQL Log Extractor
# description: This script extracts a portion of the ProxySQL log
# allow_extra_args: false
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
#    description: Optional override of the ProxySQL log file
#    placeholder: /var/log/mysql/error.log
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
# atw:
#  - PROXYSQL_CRASH
#  - CONNECTION_ISSUES
#  - QUERY_ROUTING_PROBLEMS
# ---

# proxysql_log_extractor.sh
#
# This script extracts a portion of the ProxySQL log based on a given time
# and a specified number of minutes before and after that time.
#
# Usage: ./proxysql_log_extractor.sh --time "<YYYY-MM-DD HH:MM:SS>" --minutes <minutes> [--log-file <path/to/log>] [--output <file|stdout>]
#
# Arguments:
#   --time "<YYYY-MM-DD HH:MM:SS>": The central timestamp to focus on (e.g., "2023-10-27 15:30:00").
#                                   This argument is required.
#   --minutes <minutes>: The number of minutes before and after the central timestamp to include.
#                        For example, if you provide 10, the script will show logs from 10 minutes
#                        before to 10 minutes after the given time. This argument is required.
#   --log-file <path/to/log>: Optional. The path to your ProxySQL log file.
#                             If not provided, the script defaults to /var/lib/proxysql/proxysql.log.
#   --output <file|stdout>: Optional. Where to send the output. Use 'stdout' to print to the terminal (default),
#                          or 'file' to write the output to a file named by the timestamp.
#
# Configuration:
# Default ProxySQL log path if --log-file is not specified.
DEFAULT_PROXYSQL_LOG="/var/lib/proxysql/proxysql.log"

# --- Script Functions ---

# Function to display usage information
usage() {
    echo "Usage: $0 --time \"<YYYY-MM-DD HH:MM:SS>\" --minutes <minutes> [--log-file <path/to/log>] [--output <file|stdout>]"
    echo "Example: $0 --time \"2023-10-27 15:30:00\" --minutes 5 --log-file /var/lib/proxysql/proxysql.log --output file"
    echo "         $0 --time \"2024-01-01 10:00:00\" --minutes 30"
    echo ""
    echo "This script extracts a portion of the ProxySQL log."
    echo "It will print log entries from <minutes> before to <minutes> after"
    echo "the provided timestamp."
    echo ""
    echo "Arguments:"
    echo '  --time "<YYYY-MM-DD HH:MM:SS>"   The central timestamp to focus on (required).'
    echo "  --minutes <minutes>                The number of minutes before and after the timestamp to include (required)."
    echo "  --log-file <path/to/log>           Optional. Path to the ProxySQL log file. Defaults to /var/lib/proxysql/proxysql.log."
    echo "  --output <file|stdout>             Optional. Where to send the output. Use 'stdout' to print to the terminal (default), or 'file' to write the output to a file named by the timestamp."
    exit 1
}

detect_proxysql_errorlog() {

    for cfg in /etc/proxysql.cnf /etc/proxysql/proxysql.cnf "$HOME/.config/proxysql/proxysql.cnf"; do
        if [[ -f $cfg ]]; then
            CFG_LOG=$(grep -E '^\s*errorlog\s*=' "$cfg" |
                head -n1 |
                cut -d'=' -f2 |
                tr -d '" ')
            if [[ -n $CFG_LOG ]]; then
                echo "$CFG_LOG"
                return
            fi
        fi
    done

    echo "$DEFAULT_PROXYSQL_LOG"
}

TIME_ARG=""
MINUTES_ARG=""
LOG_FILE_ARG=""
OUTPUT_MODE="stdout" # default

# Parse named arguments
while [[ $# -gt 0 ]]; do
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
        -h | --help)
            usage
            ;;
        *)
            echo "Unknown argument: $1"
            usage
            ;;
    esac
done

[[ -z $TIME_ARG || -z $MINUTES_ARG ]] && usage

if ! [[ $MINUTES_ARG =~ ^[0-9]+$ ]] || [[ $MINUTES_ARG -le 0 ]]; then
    echo "Error: --minutes must be a positive integer"
    exit 1
fi

if [[ -n $LOG_FILE_ARG ]]; then
    PROXYSQL_LOG="$LOG_FILE_ARG"
else
    PROXYSQL_LOG="$(detect_proxysql_errorlog)"
fi

if [[ ! -f $PROXYSQL_LOG || ! -r $PROXYSQL_LOG ]]; then
    echo "Error: Cannot read ProxySQL log file: $PROXYSQL_LOG"
    exit 1
fi

echo "Using ProxySQL log file: $PROXYSQL_LOG" >&2

INPUT_EPOCH=$(date -d "$TIME_ARG" +%s 2> /dev/null) || {
    echo "Invalid time format"
    exit 1
}

START_EPOCH=$((INPUT_EPOCH - (MINUTES_ARG * 60)))
END_EPOCH=$((INPUT_EPOCH + (MINUTES_ARG * 60)))

if [[ $OUTPUT_MODE == "file" ]]; then
    OUTPUT_FILE="proxysql_log_${INPUT_EPOCH}.log"
fi

awk -v start_e="$START_EPOCH" -v end_e="$END_EPOCH" '
BEGIN { print_flag = 0 }
{
    ts = substr($0, 1, 19)
    cmd = "date -d \"" ts "\" +%s 2>/dev/null"
    cmd | getline epoch
    close(cmd)

    if (epoch >= start_e && epoch <= end_e) {
        print_flag = 1
    } else if (epoch > end_e && print_flag == 1) {
        exit
    }
}
{
    if (print_flag) print
}
' "$PROXYSQL_LOG" |
    if [[ $OUTPUT_MODE == "file" ]]; then
        tee "$OUTPUT_FILE"
        echo "Output written to $OUTPUT_FILE" >&2
    else
        cat
    fi
