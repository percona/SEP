#!/usr/bin/env bash

# ---
# title: "pt-stalk"
# description: "Executes pt-stalk command"
# allow_extra_args: false
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

usage() {
    cat << EOS
Usage: $(basename "${0}") [OPTIONS]
Executes pt-stalk or stops the daemon

Command line options:

   --defaults-file         Path to MySQL defaults-file
   --pid                   pt-stalk PID file
   --log                   pt-stalk log file
   -d, --dest              Destination for the summaries.
                           Default: $(pwd)/$(hostname)-$(date +%Y-%m-%d-%H-%M-%S)
   --iterations            How many iterations to run
   --sleep                 Sleep time between iterations
   --daemon                Run pt-stalk in daemon mode
   --run-time              Set the number of seconds for --run-time, default disabled
   --system-only           Collect only operating system related captures
   --action=[start|stop]   Start or stop pt-stalk. Compresses data when stopped.
                           Default: start
   -h, --help              Show this help message

EOS
    exit "$1"
}

compress_data() {
    tar czf "${PTDEST}.tar.gz" -C "$(dirname "${PTDEST}")" "$(basename "${PTDEST}")"
}

if ! OPTS=$(getopt --options -s:d:h --longoptions 'defaults-file:,pid:,log:,dest:,iterations:,sleep:,action:,run-time:,daemon,help,system-only' -- "$@"); then
    echo "Error parsing options"
    usage 1
fi

eval set -- "$OPTS"

while [[ -n $* ]]; do
    case "$1" in
        --defaults-file)
            DEFAULTS_FILE="--defaults-file=$2"
            shift 2
            ;;
        --pid)
            PID="$2"
            shift 2
            ;;
        --log)
            LOG="$2"
            shift 2
            ;;
        -d | --dest)
            PTDEST="$2"
            shift 2
            ;;
        --iterations)
            ITERATIONS="$2"
            shift 2
            ;;
        --sleep)
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
        --action)
            ACTION="$2"
            shift 2
            ;;
        --run-time)
            RUNTIME_DURATION="$2"
            shift 2
            ;;
        -h | --help)
            usage
            ;;
        --)
            shift 1
            break
            ;;
        # Need this to catch options mess up that getopt does not recognize
        *)
            echo "Unrecognized option '$1'"
            usage 1
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

if [ $# -gt 0 ]; then
    echo "Starting pt-stalk with extra options: $*"
fi

case "$ACTION" in
    start)
        mkdir "${PTDEST}"
        if [ $IS_DAEMON -eq 1 ]; then
            pt-stalk "${DEFAULTS_FILE}" --daemonize --iterations="$ITERATIONS" --sleep="$SLEEP" --dest="${PTDEST}" --pid="${PID}" --log="${LOG}" "${SYSTEM_ONLY}" "$@"
        elif [ ${RUNTIME_DURATION} -gt 0 ]; then
            pt-stalk "${DEFAULTS_FILE}" --no-stalk --run-time="${RUNTIME_DURATION}" --sleep-collect="${LOOP_CYCLE_INTERVAL}" --iterations="$ITERATIONS" --sleep="$SLEEP" --dest="${PTDEST}" "${SYSTEM_ONLY}" "$@"
            compress_data
        else
            pt-stalk "${DEFAULTS_FILE}" --no-stalk --iterations="$ITERATIONS" --sleep="$SLEEP" --dest="${PTDEST}" "${SYSTEM_ONLY}" "$@"
            compress_data
        fi
        ;;
    stop)
        kill "$(cat "${PID}")" && compress_data
        ;;
    *)
        echo "Unrecognized action '$ACTION'"
        usage 12
        ;;
esac
