#!/usr/bin/env bash

# ---
# title: "pt-summary"
# description: "Executes pt-summary command. Extra args are passed to pt-summary after known options."
# allow_extra_args: true
# sudo: always
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

# Usage: ./pt-summary.sh [--defaults-file=path] [--dest=path] [--save-samples] [--help] [-- other args...]
# Example: ./pt-summary.sh --dest=/tmp/summary --save-samples

# Stable name for help text (Nomad/SEP may run this file as "script" or another temp name).
readonly _PT_SUMMARY_SH_NAME="pt-summary.sh"

declare DEFAULTS_FILE=""
declare PTDEST=
declare SAVE_SAMPLES=0
declare -a EXTRA_ARGS=()

usage() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: ${_PT_SUMMARY_SH_NAME} [OPTIONS]
Executes the pt-summary wrapper (Percona Toolkit).

Wrapper options:

   --defaults-file   Path to MySQL defaults-file
   -d, --dest        Destination for the samples.
                     Default: $(pwd)/$(hostname)-$(date +%Y-%m-%d-%H-%M-%S)
   --save-samples    Save samples
   -h, --help        Show this message and pt-summary --help

Any other options are passed through to pt-summary (e.g. --sleep, --config, --read-samples).

EOS
    if ((exit_code == 0)) && command -v pt-summary > /dev/null 2>&1; then
        echo "----- pt-summary --help -----"
        pt-summary --help 2>&1 || true
    fi
    exit ${exit_code}
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
                usage 1
            fi
            DEFAULTS_FILE="--defaults-file=$2"
            shift 2
            ;;
        --dest=*)
            PTDEST="${1#*=}"
            shift 1
            ;;
        -d | --dest)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for --dest"
                usage 1
            fi
            PTDEST="$2"
            shift 2
            ;;
        --save-samples)
            SAVE_SAMPLES=1
            shift 1
            ;;
        -h | --help)
            usage
            ;;
        --)
            shift
            EXTRA_ARGS=("$@")
            break
            ;;
        # Forward unknown options/args to pt-summary as passthrough options.
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

test -n "${PTDEST}" || PTDEST="$(pwd)/$(hostname)-$(date +%Y-%m-%d-%H-%M-%S)"

if [ $SAVE_SAMPLES -eq 1 ] && [ -d "${PTDEST}" ]; then
    echo Rejecting use of "${PTDEST}"
    exit 11
fi

declare -a WRAPPER_ARGS=("--dest=${PTDEST}")
if [ -n "${DEFAULTS_FILE}" ]; then
    WRAPPER_ARGS+=("${DEFAULTS_FILE}")
fi
if [ $SAVE_SAMPLES -eq 1 ]; then
    WRAPPER_ARGS+=("--save-samples")
fi

echo "Starting pt-summary with wrapper options: ${WRAPPER_ARGS[*]}"
if [ ${#EXTRA_ARGS[@]} -gt 0 ]; then
    echo "Starting pt-summary with passthrough options: ${EXTRA_ARGS[*]}"
else
    echo "Starting pt-summary with passthrough options: none"
fi

if [ $SAVE_SAMPLES -eq 1 ]; then
    mkdir "${PTDEST}"
    pt-summary "${DEFAULTS_FILE}" --save-samples="${PTDEST}" "${EXTRA_ARGS[@]}"
    tar czf "${PTDEST}.tar.gz" -C "$(dirname "${PTDEST}")" "$(basename "${PTDEST}")"
else
    pt-summary "${DEFAULTS_FILE}" "${EXTRA_ARGS[@]}"
fi
