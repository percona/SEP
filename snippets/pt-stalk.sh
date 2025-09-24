#!/usr/bin/env bash

# ---
# title: "pt-stalk"
# description: "Executes pt-stalk command"
# strict: false
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to the defaults-file
#    description: Path to the defaults-file
#  - name: pid
#    type: str
#    label: pt-stalk PID file
#    description: pt-stalk PID file
#    default: $PTDEST/pt-stalk.pid
#  - name: log
#    type: str
#    label: pt-stalk log file
#    description: pt-stalk log file
#    default: $PTDEST/pt-stalk.log
#  - name: dest
#    type: str
#    label: Destination for the summaries
#    description: Destination for the summaries
#    default: .$(pwd)/$(hostname)
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
#  - name: daemon
#    type: int
#    label: Run pt-stalk in daemon mode
#    description: Run pt-stalk in daemon mode
#    default: 0
#  - name: system-only
#    type: int
#    label: Only operating system related captures
#    description: Trigger only operating system related captures, ignoring all others
#  - name: action
#    type: str
#    label: start or stop.
#    description: Start or stop pt-stalk. Compresses data when stopped.
#    default: start
#  - name: help
#    type: int
#    label: Show help message
#    description: Show help message
#    default: 0
# ---

# Usage: ./pt-stalk.sh [--defaults-file=path]  start|stop [-- other args...]
# Example: ./pt-stalk.sh --daemon start


declare DEFAULTS_FILE=""
declare PTDEST="$(pwd)/$(hostname)"
declare PID="$PTDEST/pt-stalk.pid"
declare LOG="$PTDEST/pt-stalk.log"
declare ITERATIONS=2
declare SLEEP=30
declare IS_DAEMON=0
declare SYSTEM_ONLY=""
declare ACTION="start"

usage() {
   cat << EOS
Usage: $(basename "${0}") [OPTIONS]
Executes pt-stalk or stops the daemon

Command line options:

   --defaults-file         Path to MySQL defaults-file
   --pid                   pt-stalk PID file
   --log                   pt-stalk log file
   -d, --dest              Destination for the summaries.
                           Default: $(pwd)/$(hostname)
   --iterations            How many iterations to run
   --sleep                 Sleep time between iterations
   --daemon                Run pt-stalk in daemon mode
   --system-only           Collect only operating system related captures
   --action=[start|stop]   Start or stop pt-stalk. Compresses data when stopped.
                           Default: start
   -h, --help              Show this help message

EOS
   exit $1
}

compress_data() {
   tar czf "${PTDEST}.tar.gz" -C "$(dirname ${PTDEST})" "$(basename ${PTDEST})";
}

OPTS=$(getopt --options -s:d:h --longoptions 'defaults-file:,pid:,log:,dest:,iterations:,sleep:,action:,daemon,help,system-only' -- "$@")

if [ $? -gt 0 ]; then
   echo "Error parsing options"
   usage 1
fi

eval set -- "$OPTS"

while [[ -n "$*" ]]; do
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

if [ $# -gt 0 ]; then
   echo "Starting pt-stalk with extra options: $@"
fi

case "$ACTION" in
   start)
      mkdir -p "${PTDEST}"
      if [ $IS_DAEMON -eq 1 ]; then
         sudo pt-stalk "${DEFAULTS_FILE}" --daemonize --iterations=$ITERATIONS --sleep=$SLEEP --dest="${PTDEST}" --pid="${PID}" --log="${LOG}" "${SYSTEM_ONLY}" "$@"
      else
         sudo pt-stalk "${DEFAULTS_FILE}" --no-stalk --iterations=$ITERATIONS --sleep=$SLEEP --dest="${PTDEST}" --pid="${PID}" --log="${LOG}" "${SYSTEM_ONLY}" "$@"
         compress_data
      fi
      ;;
   stop)
      sudo kill `cat ${PID}` && compress_data
      ;;
   *)
      echo "Unrecognized action '$ACTION'"
      usage 255
      ;;
esac
