#!/usr/bin/env bash

# ---
# title: PostgreSQL Log Extractor
# description: This script extracts a portion of the PostgreSQL log containing the time of the original crash and any restart attempts.
# allow_extra_args: false
# sudo: always
# service_type: postgresql
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
#    default: 30
#  - name: log-file
#    type: str
#    label: Log file path
#    description: The path to your PostgreSQL log file.
#    placeholder: /var/log/postgresql/postgresql-16-main.log
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
#  - name: dbname
#    type: str
#    label: Target database
#    description: Database to connect to (psql --dbname). Defaults to postgres.
#    default: postgres
# atw:
#  - SERVER_CRASHED_RESTART_SUCCESSFUL
#  - SERVER_CRASHED_RESTART_NOT_SUCCESSFUL
# alerts:
#   - PostgreSQLIsDown
#   - PostgreSQLUptime
# ---

set -euo pipefail

DEFAULT_MINUTES=30

TIME_ARG=""
MINUTES_ARG=""
LOG_FILE_ARG=""
OUTPUT_MODE="stdout"
DBNAME_ARG="${PGDATABASE:-postgres}"

usage() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: $(basename "$0") --time "<YYYY-MM-DD HH:MM:SS>" [--minutes <N>] [OPTIONS]

Extract PostgreSQL log entries around a given timestamp.

Options:
  --time "<YYYY-MM-DD HH:MM:SS>"  Central timestamp (required).
  --minutes N                      Minutes before/after to include (default: ${DEFAULT_MINUTES}).
  --log-file <path>                PostgreSQL log file (auto-detected if not provided).
  --output <stdout|file>           Output destination (default: stdout).
  --dbname <db>                    Target database for psql (default: postgres).
  -h, --help                       Show this help message.
EOS
    exit "${exit_code}"
}

if ! OPTS=$(getopt --options h --longoptions 'time:,minutes:,log-file:,output:,dbname:,help' -- "$@"); then
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
        --dbname)
            DBNAME_ARG="$2"
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

export PGDATABASE="${DBNAME_ARG:-postgres}"

PSQL="psql"

if [[ -z $TIME_ARG ]]; then
    echo "Error: --time is required." >&2
    usage 1
fi

if [[ -z $MINUTES_ARG ]]; then
    MINUTES_ARG="$DEFAULT_MINUTES"
fi

if ! [[ $MINUTES_ARG =~ ^[0-9]+$ ]] || [[ $MINUTES_ARG -le 0 ]]; then
    echo "Error: --minutes must be a positive integer." >&2
    usage 1
fi

# pg_current_logfile() is the most reliable source (PostgreSQL 10+); fall back to
# composing log_directory + log_filename, then to well-known distro paths.
detect_postgresql_log() {
    local detected=""

    detected=$($PSQL -tA -c "SELECT pg_current_logfile();" 2> /dev/null | xargs 2> /dev/null || true)
    if [[ -n $detected ]]; then
        if [[ $detected != /* ]]; then
            local data_dir
            data_dir=$($PSQL -tA -c "SELECT current_setting('data_directory');" 2> /dev/null | xargs 2> /dev/null || true)
            if [[ -n $data_dir ]]; then
                detected="$data_dir/$detected"
            fi
        fi
        if [[ -f $detected ]]; then
            echo "$detected"
            return
        fi
    fi

    local log_dir log_filename data_dir
    log_dir=$($PSQL -tA -c "SELECT current_setting('log_directory');" 2> /dev/null | xargs 2> /dev/null || true)
    log_filename=$($PSQL -tA -c "SELECT current_setting('log_filename');" 2> /dev/null | xargs 2> /dev/null || true)
    if [[ -n $log_dir && -n $log_filename ]]; then
        if [[ $log_dir != /* ]]; then
            data_dir=$($PSQL -tA -c "SELECT current_setting('data_directory');" 2> /dev/null | xargs 2> /dev/null || true)
            if [[ -n $data_dir ]]; then
                log_dir="${data_dir}/${log_dir}"
            else
                log_dir=""
            fi
        fi
        if [[ -n $log_dir ]]; then
            local log_pattern candidate
            log_pattern=$(printf '%s' "$log_filename" | sed 's/%[A-Za-z]/*/g')
            candidate=$(find "$log_dir" -maxdepth 1 -type f -name "$log_pattern" -printf '%T@ %p\n' 2> /dev/null | sort -n | tail -n1 | cut -d' ' -f2- || true)
            if [[ -n $candidate && -f $candidate ]]; then
                echo "$candidate"
                return
            fi
        fi
    fi

    local matches=()
    shopt -s nullglob
    # shellcheck disable=SC2206 # intentional pathname expansion of each pattern
    for pattern in \
        '/var/log/postgresql/postgresql-*-main.log' \
        '/var/log/postgresql/postgresql-*.log' \
        '/var/lib/pgsql/*/data/log/*.log' \
        '/var/lib/pgsql/data/log/*.log' \
        '/var/lib/postgresql/*/main/log/*.log'; do
        matches=($pattern)
        if [[ ${#matches[@]} -gt 0 ]]; then
            # Pick the most recently modified file matching the pattern.
            local newest="" f
            for f in "${matches[@]}"; do
                if [[ -z $newest || $f -nt $newest ]]; then
                    newest="$f"
                fi
            done
            shopt -u nullglob
            echo "$newest"
            return
        fi
    done
    shopt -u nullglob
}

if [[ -z $LOG_FILE_ARG ]]; then
    LOG_FILE_ARG=$(detect_postgresql_log || true)
    if [[ -n $LOG_FILE_ARG ]]; then
        echo "Detected PostgreSQL log file: $LOG_FILE_ARG" >&2
    fi
fi

if [[ -z $LOG_FILE_ARG ]]; then
    echo "Error: could not auto-detect a PostgreSQL log file. Pass --log-file." >&2
    exit 1
fi

POSTGRESQL_LOG="$LOG_FILE_ARG"

if [[ ! -f $POSTGRESQL_LOG ]]; then
    echo "Error: PostgreSQL log file not found at '$POSTGRESQL_LOG'." >&2
    exit 1
fi

if [[ ! -r $POSTGRESQL_LOG ]]; then
    echo "Error: Cannot read PostgreSQL log file at '$POSTGRESQL_LOG'." >&2
    exit 1
fi

if ! INPUT_EPOCH=$(date -d "$TIME_ARG" +%s 2> /dev/null); then
    echo "Error: Could not parse time: \"$TIME_ARG\"" >&2
    exit 1
fi

START_EPOCH=$((INPUT_EPOCH - (MINUTES_ARG * 60)))
END_EPOCH=$((INPUT_EPOCH + (MINUTES_ARG * 60)))

# PostgreSQL default log_line_prefix '%m [%p] ' produces lines that begin with
# "YYYY-MM-DD HH:MM:SS.mmm TZ [pid]". CSV logs start with the same 19-char
# timestamp. Matching the leading 19 chars covers both formats; lines without a
# timestamp (continuation lines) inherit the surrounding print state.
filter_log() {
    awk -v start_e="$START_EPOCH" -v end_e="$END_EPOCH" '
BEGIN { print_flag = 0 }
{
    log_timestamp_str = ""
    if (match($0, /[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9][ T][0-9][0-9]:[0-9][0-9]:[0-9][0-9]/)) {
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
        } else if (log_epoch < start_e) {
            print_flag = 0
        }
    }
    if (print_flag == 1) print
}' "$POSTGRESQL_LOG"
}

if [[ $OUTPUT_MODE == "file" ]]; then
    OUTPUT_FILE="postgresql_log_${INPUT_EPOCH}.log"
    filter_log > "$OUTPUT_FILE"
    echo "Output written to $OUTPUT_FILE"
else
    filter_log
fi
