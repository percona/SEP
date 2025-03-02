#!/bin/bash

usage() {
  echo "Usage: $0 [--apparent-size] [-s|--summarize] [-t|--threshold=SIZE] [--exclude=PATTERN] target"
  exit 1
}

TEMP=$(getopt -o s,t: -l apparent-size,summarize,threshold:,exclude: -- "$@")
if [ $? -ne 0 ]; then
  usage
fi
eval set -- "$TEMP"

du_opts=()

while true; do
  case "$1" in
    --apparent-size)
      du_opts+=("--apparent-size")
      shift ;;
    -s|--summarize)
      du_opts+=("--summarize")
      shift ;;
    -t|--threshold|--threshold=*)
      if [[ "$1" == *=* ]]; then
        du_opts+=("$1")
        shift
      else
        du_opts+=("--threshold=$2")
        shift 2
      fi ;;
    --exclude|--exclude=*)
      if [[ "$1" == *=* ]]; then
        du_opts+=("$1")
        shift
      else
        du_opts+=("--exclude=$2")
        shift 2
      fi ;;
    --)
      shift
      break ;;
    *)
      >&2 echo "Invalid option: $1"
      usage ;;
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
