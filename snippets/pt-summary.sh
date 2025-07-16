#!/usr/bin/env bash

# ---
# title: "pt-summary"
# description: "Executes pt-summary command"
# strict: false
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to the defaults-file
#    description: Path to the defaults-file
#  - name: dest
#    type: str
#    label: Destination for the summaries
#    description: Destination for the summaries
#    default: .$(pwd)/$(hostname)-$(date +%g-%m-%d-%H-%M-%S)"
#  - name: save-samples
#    type: int
#    label: Save samples
#    description: Save samples
#    default: 0
#  - name: help
#    type: int
#    label: Show help message
#    description: Show help message
#    default: 0
# ---

# Usage: ./pt-summary.sh [--defaults-file=path] [--dest=path] [--save-samples] [--help] [-- other args...]
# Example: ./pt-summary.sh --dest=/tmp/summary --save-samples

declare DEFAULTS_FILE=""
declare PTDEST="$(pwd)/$(hostname)-$(date +%g-%m-%d-%H-%M-%S)"
declare SAVE_SAMPLES=0

usage() {
   cat << EOS
Usage: $(basename "${0}") [OPTIONS]
Executes pt-summary script

Command line options:

   --defaults-file   Path to MySQL defaults-file
   -d, --dest        Destination for the samples. 
                     Default: .$(pwd)/$(hostname)-$(date +%g-%m-%d-%H-%M-%S)
   --save-samples    Save samples
   -h, --help        Show this help message

EOS
   exit $1
}

OPTS=$(getopt --options -d:h --longoptions 'dest:,save-samples,help' -- "$@")

eval set -- "$OPTS"

while [[ -n "$*" ]]; do
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
         usage
         ;;
      --)
         break
         ;;
      *)
         echo "Unrecognized option '$1'"
         usage 255
         ;;
   esac
done

if [ $# -gt 0 ]; then
   echo "Starting pt-summary with extra options: $@"
fi

if [ $SAVE_SAMPLES -eq 1 ]; then
   mkdir -p "${PTDEST}"
   sudo pt-summary ${DEFAULTS_FILE} --save-samples="${PTDEST}" "$@"
   tar czf "${PTDEST}.tar.gz" -C "$(dirname ${PTDEST})" "$(basename ${PTDEST})"
else
   sudo pt-summary ${DEFAULTS_FILE} "$@"
fi

