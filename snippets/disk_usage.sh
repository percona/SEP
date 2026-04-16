#!/bin/bash

# ---
# title: "Disk Usage"
# description: "This snippet displays the device usage for the specified target."
# allow_extra_args: false
# sudo: optional
# parameters:
#  - name: apparent-size
#    type: bool
#    label: Print apparent sizes
#    description: print apparent sizes rather than device usage
#  - name: summarize
#    type: bool
#    label: Summarize
#    description: display only a total for each target
#    default: true
#  - name: threshold
#    type: str
#    label: Threshold Size
#    description: exclude entries based on a given size
#    placeholder: e.g. 1024, 1KB, 200MB
#    pattern: ^[0-9]+[KMGTPE]?B?$
#  - name: exclude
#    type: str
#    label: Exclude Pattern
#    description: exclude files that match the specified shell pattern
#    placeholder: e.g. *.py; .git
#  - name: time
#    type: str
#    description: show time of the specified type
#    label: Show time
#    choices:
#      - value: mtime
#        label: Last modification time
#      - value: ctime
#        label: Last metadata change time
#      - value: atime
#        label: Last access time
#  - name: target
#    type: str
#    label: Target
#    description: the file or folder to check device usage for
#    placeholder: e.g. /home/user/folder/; file.zip
#    positional: true
#    required: true
# service_type: generic
# alerts:
#   - HighDiskUsage
#   - BackupFailed
#   - StaleBackup
#   - StaleBackupLog
#   - StaleUpload
#   - StaleUploadLog
# ---

usage() {
    echo "Usage: $0 [--apparent-size] [-s|--summarize] [-t|--threshold=SIZE] [--exclude=PATTERN] [--time=TIME] target"
    echo "       TIME can be atime, ctime, or mtime."
    exit 1
}

if ! TEMP=$(getopt -o s,t: -l apparent-size,summarize,threshold:,exclude:,time: -- "$@"); then
    usage
fi
eval set -- "$TEMP"

du_opts=()

while true; do
    case "$1" in
        --apparent-size)
            du_opts+=("--apparent-size")
            shift
            ;;
        -s | --summarize)
            du_opts+=("--summarize")
            shift
            ;;
        -t | --threshold | --threshold=*)
            if [[ $1 == *=* ]]; then
                du_opts+=("$1")
                shift
            else
                du_opts+=("--threshold=$2")
                shift 2
            fi
            ;;
        --exclude | --exclude=*)
            if [[ $1 == *=* ]]; then
                du_opts+=("$1")
                shift
            else
                du_opts+=("--exclude=$2")
                shift 2
            fi
            ;;
        --time | --time=*)
            if [[ $1 == *=* ]]; then
                time_value="${1#*=}"
                shift
            else
                time_value="$2"
                shift 2
            fi
            if [[ $time_value == "mtime" ]]; then
                du_opts+=("--time")
            else
                du_opts+=("--time=$time_value")
            fi
            ;;
        --)
            shift
            break
            ;;
        *)
            >&2 echo "Invalid option: $1"
            usage
            ;;
    esac
done

if [ $# -lt 1 ]; then
    usage
fi

target="$1"
shift

if [ ! -e "$target" ]; then
    >&2 echo "Error: '$target' does not exist."
    exit 1
fi

du "${du_opts[@]}" "$target"
