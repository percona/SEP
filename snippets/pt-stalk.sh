#!/usr/bin/env bash

# ---
# title: "pt-stalk"
# description: "Executes pt-stalk command. Extra args are passed to pt-stalk after known options."
# allow_extra_args: true
# sudo: always
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to the defaults-file
#    description: Path to the defaults-file
#  - name: run-time
#    type: int
#    ge: 0
#    le: 43200
#    label: How many seconds to run for
#    description: How many iterations to run, used with --run-time
#  - name: iterations
#    type: int
#    label: How many iterations to run
#    description: How many iterations to run
#    default: 2
#  - name: sleep
#    type: int
#    label: Sleep time between iterations
#    description: Sleep time between iterations
#    default: 30
#  - name: system-only
#    type: bool
#    label: Only operating system related captures
#    description: Trigger only operating system related captures, ignoring all others
#  - name: help
#    type: bool
#    label: Show help message
#    description: Show help message
# atw:
#  - OVERALL_SLOWNESS
#  - NOT_RESPONDING
#  - WRITES_ARE_BLOCKED
#  - PERFORMANCE_OTHER
#  - TEMPORARY_STALLS
#  - NATIVE_ASYNC_REPLICATION
#  - GALERA
#  - GROUP_REPLICATION
# ---

# Usage: ./pt-stalk.sh [--defaults-file=path]  start|stop [-- other args...]
# Example: ./pt-stalk.sh --daemon start

readonly _PT_STALK_SH_NAME="pt-stalk.sh"

declare DEFAULTS_FILE=""
declare PTDEST=
declare PID=
declare LOG=
declare IS_DAEMON=0
declare SYSTEM_ONLY=""
declare ACTION="start"

declare -i ITERATIONS=2
declare -i LOOP_CYCLE_INTERVAL=60
declare -i RUNTIME_DURATION=0
declare -i SLEEP=30
declare -a EXTRA_ARGS=()

usage_short() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: ${_PT_STALK_SH_NAME} [OPTIONS]
Executes pt-stalk or stops the daemon

Command line options:

   --defaults-file         Path to MySQL defaults-file
   --pid                   pt-stalk PID file
   --log                   pt-stalk log file
   -d, --dest              Destination for the summaries.
                           Default: $(pwd)/$(hostname)-$(date +%Y-%m-%d-%H-%M-%S)
   --iterations            How many iterations to run
   --sleep                 Sleep time between iterations
   -s                      Short form for --sleep (seconds)
   --daemon                Run pt-stalk in daemon mode
   --run-time              Set the number of seconds for --run-time, default disabled
   --system-only           Collect only operating system related captures
   --action=[start|stop]   Start or stop pt-stalk. Compresses data when stopped.
                           Default: start
   -h, --help              Show full help (includes pt-stalk --help)

Any other options are passed through to pt-stalk (e.g. --config, --mysql-only, --variable).

EOS
    exit ${exit_code}
}

usage_full() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: ${_PT_STALK_SH_NAME} [OPTIONS]
Executes the pt-stalk wrapper (Percona Toolkit).

Wrapper options:

   --defaults-file         Path to MySQL defaults-file
   --pid                   pt-stalk PID file
   --log                   pt-stalk log file
   -d, --dest              Destination for the summaries.
                           Default: $(pwd)/$(hostname)-$(date +%Y-%m-%d-%H-%M-%S)
   --iterations            How many iterations to run
   --sleep, -s             Sleep time between iterations
   --daemon                Run pt-stalk in daemon mode
   --run-time              Seconds for collection run-time mode
   --system-only           Collect only operating system related captures
   --action=[start|stop]   Start or stop pt-stalk
   -h, --help              Show this message and pt-stalk --help

Use -- before arguments that must be passed verbatim. Other flags are forwarded to pt-stalk.

EOS
    if ((exit_code == 0)) && command -v pt-stalk > /dev/null 2>&1; then
        echo "----- pt-stalk --help -----"
        pt-stalk --help 2>&1 || true
    fi
    exit ${exit_code}
}

compress_data() {
    tar czf "${PTDEST}.tar.gz" -C "$(dirname "${PTDEST}")" "$(basename "${PTDEST}")"
}

# Log passthrough args only when present (same idea as the original script).
maybe_log_extra_args() {
    if [[ $ACTION != start ]] || [[ $IS_DAEMON -eq 1 ]]; then
        return 0
    fi
    if [ ${#EXTRA_ARGS[@]} -gt 0 ]; then
        echo "Starting pt-stalk with extra options: ${EXTRA_ARGS[*]}"
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --defaults-file=*)
            DEFAULTS_FILE="--defaults-file=${1#*=}"
            shift 1
            ;;
        --defaults-file)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for --defaults-file"
                usage_short 1
            fi
            DEFAULTS_FILE="--defaults-file=$2"
            shift 2
            ;;
        --pid=*)
            PID="${1#*=}"
            shift 1
            ;;
        --pid)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for --pid"
                usage_short 1
            fi
            PID="$2"
            shift 2
            ;;
        --log=*)
            LOG="${1#*=}"
            shift 1
            ;;
        --log)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for --log"
                usage_short 1
            fi
            LOG="$2"
            shift 2
            ;;
        --dest=*)
            PTDEST="${1#*=}"
            shift 1
            ;;
        -d | --dest)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for --dest"
                usage_short 1
            fi
            PTDEST="$2"
            shift 2
            ;;
        --iterations=*)
            ITERATIONS="${1#*=}"
            shift 1
            ;;
        --iterations)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for --iterations"
                usage_short 1
            fi
            ITERATIONS="$2"
            shift 2
            ;;
        --sleep=*)
            SLEEP="${1#*=}"
            shift 1
            ;;
        --sleep)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for --sleep"
                usage_short 1
            fi
            SLEEP="$2"
            shift 2
            ;;
        -s)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for -s"
                usage_short 1
            fi
            SLEEP="$2"
            shift 2
            ;;
        --daemon)
            IS_DAEMON=1
            shift 1
            ;;
        --system-only)
            SYSTEM_ONLY="--system-only"
            shift 1
            ;;
        --action=*)
            ACTION="${1#*=}"
            shift 1
            ;;
        --action)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for --action"
                usage_short 1
            fi
            ACTION="$2"
            shift 2
            ;;
        --run-time=*)
            RUNTIME_DURATION="${1#*=}"
            shift 1
            ;;
        --run-time)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for --run-time"
                usage_short 1
            fi
            RUNTIME_DURATION="$2"
            shift 2
            ;;
        -h | --help)
            usage_full
            ;;
        --)
            shift
            EXTRA_ARGS=("$@")
            break
            ;;
        -*)
            EXTRA_ARGS=("$@")
            break
            ;;
        *)
            EXTRA_ARGS=("$@")
            break
            ;;
    esac
done

test -n "${PTDEST}" || {
    PTDEST="$(pwd)/$(hostname)-$(date +%Y-%m-%d-%H-%M-%S)"
    PID="$PTDEST/pt-stalk.pid"
    LOG="$PTDEST/pt-stalk.log"
}

if [ -d "${PTDEST}" ]; then
    echo Rejecting use of "${PTDEST}"
    exit 11
fi

maybe_log_extra_args

case "$ACTION" in
    start)
        mkdir "${PTDEST}"
        if [ $IS_DAEMON -eq 1 ]; then
            pt-stalk "${DEFAULTS_FILE}" --daemonize --iterations="$ITERATIONS" --sleep="$SLEEP" --dest="${PTDEST}" --pid="${PID}" --log="${LOG}" "${SYSTEM_ONLY}" "${EXTRA_ARGS[@]}" || exit $?
        elif [ ${RUNTIME_DURATION} -gt 0 ]; then
            pt-stalk "${DEFAULTS_FILE}" --no-stalk --run-time="${RUNTIME_DURATION}" --sleep-collect="${LOOP_CYCLE_INTERVAL}" --iterations="$ITERATIONS" --sleep="$SLEEP" --dest="${PTDEST}" "${SYSTEM_ONLY}" "${EXTRA_ARGS[@]}" || exit $?
            compress_data
        else
            pt-stalk "${DEFAULTS_FILE}" --no-stalk --iterations="$ITERATIONS" --sleep="$SLEEP" --dest="${PTDEST}" "${SYSTEM_ONLY}" "${EXTRA_ARGS[@]}" || exit $?
            compress_data
        fi
        ;;
    stop)
        kill "$(cat "${PID}")" && compress_data
        ;;
    *)
        echo "Unrecognized action '$ACTION'"
        usage_short 12
        ;;
esac
