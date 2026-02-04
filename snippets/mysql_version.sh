#!/usr/bin/env bash

# ---
# title: "mysql_version"
# description: "Returns the MySQL version"
# allow_extra_args: true
# parameters:
#  - name: basedir
#    type: str
#    label: Path to the MySQL base directory
#    description: Path to the MySQL base directory
#    default: ""
#  - name: output-format
#    type: str
#    label: Output format
#    description: Output format (json, full_string, number)
#    default: "full_string"
#  - name: help
#    type: int
#    label: Show help message
#    description: Show help message
#    default: 0
# ---

# Usage: ./mysql_version.sh [--basedir=path] [--output-format=format] [--help]
# Example: ./mysql_version.sh --basedir=/tmp/12345 --output-format=json

declare BASEDIR=""
declare OUTPUT_FORMAT="full_string"
declare MYSQLD=""

usage() {
    cat << EOS
Usage: $(basename "${0}") [OPTIONS]
Returns the MySQL version.

This snippet runs "mysqld --version" command to get the MySQL version.
By default, it queries mysqld binary installed in the default location
for your operating system and returns the full version string as
printed by the command. You can specify a different MySQL base directory
or change the output format.

Command line options:

   --basedir         Path to the MySQL base directory
   --output-format   Output format (json, full_string, number)
                     Default: full_string
   -h, --help        Show this help message

EOS
    exit "$1"
}

if ! OPTS=$(getopt --options -h --longoptions 'basedir:,output-format:,help' -- "$@"); then
    echo "Error parsing options"
    usage 1
fi

eval set -- "$OPTS"

while [[ -n $* ]]; do
    case "$1" in
        --basedir)
            BASEDIR="$2"
            shift 2
            ;;
        --output-format)
            OUTPUT_FORMAT="$2"
            shift 2
            ;;
        -h | --help)
            usage
            ;;
        --)
            break
            ;;
        # Need this to catch options mess up that getopt does not recognize
        *)
            echo "Unrecognized option '$1'"
            usage 1
            ;;
    esac
done

if [[ -z $BASEDIR ]]; then
    # Check if mysqld command is available
    MYSQLD=$(command -v mysqld)
    if [[ -z $MYSQLD ]]; then
        echo "mysqld command not found and option --basedir was not provided. Please ensure MySQL is installed and in your PATH."
        exit 1
    fi
else
    # Check if mysqld command is available in the specified base directory
    MYSQLD="$(command -v "$BASEDIR"/{bin,sbin,libexec}/mysqld)"
    if [[ -z $MYSQLD ]]; then
        echo "mysqld command not found in the specified base directory: $BASEDIR. Please ensure the path is correct."
        exit 1
    fi
fi

if ! VERSION_STRING=$("$MYSQLD" --version 2> /dev/null); then
    echo "Failed to retrieve MySQL version. Please check if mysqld is installed correctly."
    exit 1
fi

case "$OUTPUT_FORMAT" in
    full_string)
        echo "${VERSION_STRING}"
        ;;
    number)
        # Extract the version number from the full string
        VERSION_NUMBER=$(echo "${VERSION_STRING}" | grep -oP '(?<=Ver )\d+\.\d+\.\d+(-\w+)?')
        echo "${VERSION_NUMBER}"
        ;;
    json)
        VERSION_NUMBER=$(echo "${VERSION_STRING}" | grep -oP '(?<=Ver )\d+\.\d+\.\d+(-\w+)?')
        PLATFORM=$(echo "${VERSION_STRING}" | grep -oP '(?<=for ).+?(?= \()')
        VERSION_COMMENT=$(echo "${VERSION_STRING}" | grep -oP '(?<=\().+(?=\))')
        echo "{\"version\": \"${VERSION_NUMBER}\", \"platform\": \"${PLATFORM}\", \"version_comment\": \"${VERSION_COMMENT}\"}"
        ;;
    *)
        echo "Invalid output format: ${OUTPUT_FORMAT}. Use json, full_string, or number."
        exit 1
        ;;
esac
