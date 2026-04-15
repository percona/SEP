#!/usr/bin/env bash

# ---
# title: MHA Log Extractor
# description: This script extracts a portion of the MHA (Master High Availability) log based on a given time and a specified number of minutes before and after that time.
# allow_extra_args: false
# sudo: optional
# service_type: mysql
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
#    description: The path to your MHA log file
#    placeholder: /var/log/mha/manager.log
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

# mha_logs_extractor.sh
#
# This script extracts a portion of the MHA log based on a given time
# and a specified number of minutes before and after that time.
#
# Usage: ./mha_logs_extractor.sh --time "<YYYY-MM-DD HH:MM:SS>" --minutes <minutes> [--log-file <path/to/log>] [--output <file|stdout>]
#
# Arguments:
#   --time "<YYYY-MM-DD HH:MM:SS>": The central timestamp to focus on (e.g., "2023-10-27 15:30:00").
#                                   This argument is required.
#   --minutes <minutes>: The number of minutes before and after the central timestamp to include.
#                        For example, if you provide 10, the script will show logs from 10 minutes
#                        before to 10 minutes after the given time. This argument is required.
#   --log-file <path/to/log>: Optional. The path to your MHA log file.
#                             If not provided, the script defaults to /var/log/mha/manager.log.
#   --output <file|stdout>: Optional. Where to send the output. Use 'stdout' to print to the terminal (default),
#                          or 'file' to write the output to a file named by the timestamp.
#
# Configuration:
# Default MHA log path if --log-file is not specified.
DEFAULT_MHA_LOG="/var/log/mha/manager.log"

# --- Script Functions ---

# Function to display usage information
usage() {
    echo "Usage: $0 --time \"<YYYY-MM-DD HH:MM:SS>\" --minutes <minutes> [--log-file <path/to/log>] [--output <file|stdout>]"
    echo "Example: $0 --time \"2023-10-27 15:30:00\" --minutes 5 --log-file /var/log/mha/manager.log --output file"
    echo "         $0 --time \"2024-01-01 10:00:00\" --minutes 30"
    echo ""
    echo "This script extracts a portion of the MHA log."
    echo "It will print log entries from <minutes> before to <minutes> after"
    echo "the provided timestamp."
    echo ""
    echo "Arguments:"
    echo '  --time "<YYYY-MM-DD HH:MM:SS>"   The central timestamp to focus on (required).'
    echo "  --minutes <minutes>                The number of minutes before and after the timestamp to include (required)."
    echo "  --log-file <path/to/log>           Optional. Path to the MHA log file. Defaults to /var/log/mha/manager.log."
    echo "  --output <file|stdout>             Optional. Where to send the output. Use 'stdout' to print to the terminal (default), or 'file' to write the output to a file named by the timestamp."
    exit 1
}

# --- Main Script Logic ---

# Initialize variables for named arguments
TIME_ARG=""
MINUTES_ARG=""
LOG_FILE_ARG=""
OUTPUT_MODE="stdout" # default

# Parse named arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --time)
            if [ -z "$2" ]; then
                echo "Error: --time requires an argument."
                usage
            fi
            TIME_ARG="$2"
            shift # Shift past the argument name
            shift # Shift past the argument value
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

# 1. Validate required arguments
if [ -z "$TIME_ARG" ]; then
    echo "Error: --time argument is required."
    usage
fi

if [ -z "$MINUTES_ARG" ]; then
    echo "Error: --minutes argument is required."
    usage
fi

# Check if MINUTES_ARG is a positive integer
if ! [[ $MINUTES_ARG =~ ^[0-9]+$ ]] || [ "$MINUTES_ARG" -le 0 ]; then
    echo "Error: --minutes must be a positive integer."
    usage
fi

# Determine the actual log file path
MHA_LOG="${LOG_FILE_ARG:-$DEFAULT_MHA_LOG}"

# Check if the log file exists and is readable
if [ ! -f "$MHA_LOG" ]; then
    echo "Error: MHA log file not found at '$MHA_LOG'."
    echo "Please ensure the file exists and the path is correct."
    exit 1
fi

if [ ! -r "$MHA_LOG" ]; then
    echo "Error: Cannot read MHA log file at '$MHA_LOG'."
    echo "Please check file permissions for '$MHA_LOG'."
    exit 1
fi

# 2. Calculate the start and end timestamps in epoch format
#    We use 'date -d' to parse the input time and perform arithmetic.
#    '%s' gives the Unix epoch time (seconds since 1970-01-01 00:00:00 UTC).

# Convert input time to epoch
# Check if date parsing was successful
if ! INPUT_EPOCH=$(date -d "$TIME_ARG" +%s 2> /dev/null); then
    echo "Error: Could not parse the provided time format: \"$TIME_ARG\""
    echo 'Please ensure the time is in a valid format, e.g., "YYYY-MM-DD HH:MM:SS"'
    exit 1
fi

if [[ $OUTPUT_MODE == "file" ]]; then
    OUTPUT_FILE="mha_logs_${INPUT_EPOCH}.log"
fi

# Calculate start and end epoch times
START_EPOCH=$((INPUT_EPOCH - (MINUTES_ARG * 60)))
END_EPOCH=$((INPUT_EPOCH + (MINUTES_ARG * 60)))

# Optional: Uncomment for debugging purposes
# echo "Searching logs from: $(date -d "@$START_EPOCH" +"%Y-%m-%d %H:%M:%S")"
# echo "To: $(date -d "@$END_EPOCH" +"%Y-%m-%d %H:%M:%S")"
# echo "---"

# 3. Filter the log file using awk
#    - For each line, extract the first 19 characters as the timestamp string (assumed format: YYYY-MM-DD HH:MM:SS).
#    - Use the external 'date' command to convert this timestamp to epoch seconds.
#    - If the epoch is within the [START_EPOCH, END_EPOCH] window, set 'print_flag' to 1 (start printing lines).
#    - If the epoch exceeds END_EPOCH and we were printing, exit early (log is assumed chronological).
#    - While 'print_flag' is 1, print all lines—including those that do not start with a timestamp—so multi-line log entries are included as long as their initial timestamped line was in range.

AWK_CMD="awk -v start_e=\"$START_EPOCH\" -v end_e=\"$END_EPOCH\" '
BEGIN {
    # Initialize a flag to indicate if we should start printing lines
    print_flag = 0;
}
{
    # Extract the timestamp from the beginning of the line (first 19 characters)
    log_timestamp_str = substr(\$0, 1, 19);

    # Convert log timestamp to epoch using the external date command.
    # We use double quotes around the timestamp within the date command for robustness.
    cmd = \"date -d \\\"\" log_timestamp_str \"\\\" +%s 2>/dev/null\";
    cmd | getline log_epoch;
    close(cmd); # Important: Close the pipe to the date command to avoid issues with too many open pipes

    # Compare log epoch with our desired range
    if (log_epoch >= start_e && log_epoch <= end_e) {
        print_flag = 1; # Start printing lines as we are within the desired time window
    } else if (log_epoch > end_e) {
        # If we have passed the end time, and we were previously printing,
        # it means we have gone past the relevant log entries.
        # Log files are typically chronological, so we can exit.
        if (print_flag == 1) {
             exit; # Exit awk, no need to process further lines
        }
    }
}
{
    # Print the current line if the 'print_flag' is set.
    # This ensures that all lines, including multi-line error messages that
    # do not start with a timestamp, are included if they fall within the range
    # of a previously timestamped line.
    if (print_flag == 1) {
        print;
    }
}' \"$MHA_LOG\""

if [[ $OUTPUT_MODE == "file" ]]; then
    eval "$AWK_CMD > \"$OUTPUT_FILE\""
    echo "Output written to $OUTPUT_FILE"
else
    eval "$AWK_CMD"
fi
