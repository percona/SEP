#!/usr/bin/env bash

# ---
# title: "pt-pmp (MongoDB)"
# description: "Collects aggregated stack traces from a MongoDB process using pt-pmp. Defaults to attaching to the running mongod and using the eu-stack (pteu) dumper, which requires the elfutils/eu-stack package to be installed on the target host. Extra args are passed to pt-pmp after known options."
# allow_extra_args: true
# sudo: always
# parameters:
#  - name: pid
#    type: int
#    label: Process PID
#    description: PID of the MongoDB process to attach to. If omitted, the script auto-detects the running mongod via pgrep.
#  - name: binary
#    type: str
#    label: Binary name
#    description: Process name to look up when --pid is not provided. Defaults to mongod.
#    default: mongod
#  - name: dumper
#    type: str
#    label: Dumper backend
#    description: Backend used by pt-pmp to dump stack traces. pteu uses eu-stack (recommended), gdb uses gdb.
#    default: pteu
#    choices:
#      - pteu
#      - gdb
#  - name: iterations
#    type: int
#    ge: 1
#    le: 1000
#    label: Iterations
#    description: Number of stack samples to collect.
#    default: 10
#  - name: interval
#    type: int
#    ge: 0
#    le: 3600
#    label: Interval
#    description: Seconds between samples.
#    default: 1
#  - name: help
#    type: bool
#    label: Show help message
#    description: Show help message
# service_type: mongodb
# alerts:
#   - MongoDBInstanceNotAvailable
#   - MongoDBNoPrimary
#   - MongoDBReplicaState
# ---

# Usage: ./mongodb_pt_pmp.sh [--pid PID] [--binary mongod] [--dumper pteu|gdb] [--iterations N] [--interval S] [--dest DIR] [-- other args...]
# Example: ./mongodb_pt_pmp.sh --iterations 5 --interval 2

declare TARGET_PID=""
declare BINARY="mongod"
declare DUMPER="pteu"
declare PTDEST=""
declare -i ITERATIONS=10
declare -i INTERVAL=1

usage() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: $(basename "${0}") [OPTIONS] [-- extra pt-pmp args]
Collect aggregated stack traces from a MongoDB process with pt-pmp.

Command line options:

   --pid PID           PID of the MongoDB process to attach to.
                       If omitted, auto-detects via 'pgrep -x \$BINARY'.
   --binary NAME       Process name used for auto-detection. Default: mongod
   --dumper BACKEND    pt-pmp dumper backend: pteu (eu-stack, recommended)
                       or gdb. Default: pteu
   --iterations N      Number of stack samples to collect. Default: 10
   --interval S        Seconds between samples. Default: 1
   -d, --dest DIR      Destination directory for the saved samples.
                       Default: \$(pwd)/\$(hostname)-\$(date +%Y-%m-%d-%H-%M-%S)
   -h, --help          Show this help message

Notes:
   The 'pteu' dumper requires the eu-stack tool from the elfutils package
   (e.g. 'apt install elfutils' or 'yum install elfutils'). pt-pmp itself
   is provided by the percona-toolkit package.
EOS
    exit ${exit_code}
}

if ! OPTS=$(getopt --options -d:h --longoptions 'pid:,binary:,dumper:,iterations:,interval:,dest:,help' -- "$@"); then
    echo "Error parsing options"
    usage 1
fi

eval set -- "$OPTS"

while [[ -n $* ]]; do
    case "$1" in
        --pid)
            TARGET_PID="$2"
            shift 2
            ;;
        --binary)
            BINARY="$2"
            shift 2
            ;;
        --dumper)
            DUMPER="$2"
            shift 2
            ;;
        --iterations)
            ITERATIONS="$2"
            shift 2
            ;;
        --interval)
            INTERVAL="$2"
            shift 2
            ;;
        -d | --dest)
            PTDEST="$2"
            shift 2
            ;;
        -h | --help)
            usage
            ;;
        --)
            shift 1
            break
            ;;
        *)
            echo "Unrecognized option '$1'"
            usage 1
            ;;
    esac
done

if ! command -v pt-pmp > /dev/null 2>&1; then
    echo "pt-pmp not found. Install the percona-toolkit package on the target host." >&2
    exit 2
fi

if [ "${DUMPER}" = "pteu" ] && ! command -v eu-stack > /dev/null 2>&1; then
    echo "eu-stack not found but --dumper=pteu was requested." >&2
    echo "Install elfutils on the target host (apt install elfutils / yum install elfutils)," >&2
    echo "or rerun with --dumper gdb." >&2
    exit 3
fi

if [ -z "${TARGET_PID}" ]; then
    TARGET_PID="$(pgrep -x "${BINARY}" | head -n 1 || true)"
fi

if [ -z "${TARGET_PID}" ]; then
    echo "No PID provided and no running '${BINARY}' process found." >&2
    exit 4
fi

if ! kill -0 "${TARGET_PID}" 2> /dev/null; then
    echo "PID ${TARGET_PID} is not a running process." >&2
    exit 5
fi

test -n "${PTDEST}" || PTDEST="$(pwd)/$(hostname)-$(date +%Y-%m-%d-%H-%M-%S)"

if [ -d "${PTDEST}" ]; then
    echo "Rejecting use of existing destination directory '${PTDEST}'" >&2
    exit 11
fi

mkdir "${PTDEST}"
SAMPLES_FILE="${PTDEST}/pt-pmp.log"

echo "Running pt-pmp against PID ${TARGET_PID} (${BINARY}) with --dumper=${DUMPER}, iterations=${ITERATIONS}, interval=${INTERVAL}"
echo "Saving samples to ${SAMPLES_FILE}"
if [ $# -gt 0 ]; then
    echo "Extra pt-pmp args: $*"
fi

pt-pmp \
    --pid "${TARGET_PID}" \
    --binary "${BINARY}" \
    --dumper "${DUMPER}" \
    --iterations "${ITERATIONS}" \
    --interval "${INTERVAL}" \
    --save-samples "${SAMPLES_FILE}" \
    "$@"

tar czf "${PTDEST}.tar.gz" -C "$(dirname "${PTDEST}")" "$(basename "${PTDEST}")"
echo "Output archive: ${PTDEST}.tar.gz"
