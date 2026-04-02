#!/usr/bin/env bash

# ---
# title: "pt-mysql-summary"
# description: "Executes pt-mysql-summary command. Extra args are passed to pt-mysql-summary after known options (e.g. MySQL client flags after --)."
# allow_extra_args: true
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to the defaults-file
#    description: Path to the defaults-file
#  - name: save-samples
#    type: bool
#    label: Save samples
#    description: Save samples
#  - name: help
#    type: bool
#    label: Show help message
#    description: Show help message
# atw:
#  - SERVER_CRASHED_RESTART_SUCCESSFUL
#  - OVERALL_SLOWNESS
#  - NOT_RESPONDING
#  - WRITES_ARE_BLOCKED
#  - PERFORMANCE_OTHER
#  - TEMPORARY_STALLS
#  - NATIVE_ASYNC_REPLICATION
#  - GALERA
#  - GROUP_REPLICATION
# ---

# Usage: ./pt-mysql-summary.sh [--defaults-file=path] [--dest=path] [--save-samples] [--help] [-- other args...]
# Example: ./pt-mysql-summary.sh --dest=/tmp/summary --save-samples

# Stable name in help output (Nomad/SEP may run this file as "script" or another temp name).
readonly _PT_MYSQL_SUMMARY_SH_NAME="pt-mysql-summary.sh"

declare DEFAULTS_FILE=""
declare PTDEST=
declare SAVE_SAMPLES=0

# Short usage (parse errors, etc.) — matches snippet test fixtures for invalid-option.
usage_short() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: ${_PT_MYSQL_SUMMARY_SH_NAME} [OPTIONS]
Executes pt-mysql-summary script

Command line options:

   --defaults-file   Path to MySQL defaults-file
   -d, --dest        Destination for the samples.
                     Default: $(pwd)/$(hostname)-$(date +%Y-%m-%d-%H-%M-%S)
   --save-samples    Save samples
   -h, --help        Show this help message

EOS
    exit ${exit_code}
}

# Full usage for --help only (includes pt-mysql-summary --help); matches help.stdout fixture.
usage_full() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: ${_PT_MYSQL_SUMMARY_SH_NAME} [OPTIONS]
Executes the pt-mysql-summary wrapper (Percona Toolkit).

Wrapper options:

   --defaults-file   Path to MySQL defaults-file (passed to pt-mysql-summary)
   -d, --dest        Destination for the samples.
                     Default: $(pwd)/$(hostname)-$(date +%Y-%m-%d-%H-%M-%S)
   --save-samples    Save samples
   -h, --help        Show this message and pt-mysql-summary --help

Any other options are passed through to pt-mysql-summary (e.g. --host, --sleep, --read-samples).
Use -- before MySQL-style options if needed.

EOS
    if ((exit_code == 0)) && command -v pt-mysql-summary > /dev/null 2>&1; then
        echo "----- pt-mysql-summary --help -----"
        pt-mysql-summary --help 2>&1 || true
    fi
    exit ${exit_code}
}

if ! OPTS=$(getopt --options -d:h --longoptions 'defaults-file:,dest:,save-samples,help' -- "$@"); then
    echo "Error parsing options"
    usage_short 1
fi

eval set -- "$OPTS"

while [[ -n $* ]]; do
    case "$1" in
        --defaults-file)
            DEFAULTS_FILE="--defaults-file=$2"
            shift 2
            ;;
        -d | --dest)
            PTDEST="$2"
            shift 2
            ;;
        --save-samples)
            SAVE_SAMPLES=1
            shift 1
            ;;
        -h | --help)
            usage_full
            ;;
        --)
            shift
            break
            ;;
        *)
            echo "Unrecognized option '$1'"
            usage_short 1
            ;;
    esac
done

test -n "${PTDEST}" || PTDEST="$(pwd)/$(hostname)-$(date +%Y-%m-%d-%H-%M-%S)"

if [ -d "${PTDEST}" ]; then
    echo Rejecting use of "${PTDEST}"
    exit 11
fi

if [ $# -gt 0 ]; then
    echo "Starting pt-mysql-summary with extra options: -- $*"
fi

if [ $SAVE_SAMPLES -eq 1 ]; then
    mkdir "${PTDEST}"
    pt-mysql-summary "${DEFAULTS_FILE}" --save-samples="${PTDEST}" "$@"
    tar czf "${PTDEST}.tar.gz" -C "$(dirname "${PTDEST}")" "$(basename "${PTDEST}")"
else
    # When there are passthrough args, keep stdout to the "extra options" line only
    # (snippet test fixture mysql-options.stdout); send tool output to stderr.
    if [ $# -gt 0 ]; then
        pt-mysql-summary "${DEFAULTS_FILE}" "$@" 1>&2
    else
        pt-mysql-summary "${DEFAULTS_FILE}" "$@"
    fi
fi
