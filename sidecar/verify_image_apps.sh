#!/usr/bin/env bash
# Assert an already-built image's app set, by piping sidecar/verify_image_apps.py
# into that image's own interpreter. Usage: verify_image_apps.sh <image> restricted.
# Set CONTAINER_RUNTIME=podman for the Jenkins agent; CI uses the docker default.
set -o errexit -o nounset -o pipefail

if [ "$#" -ne 2 ]; then
    echo "usage: ${0##*/} <image> restricted" >&2
    exit 2
fi

image="$1"
mode="$2"
runtime="${CONTAINER_RUNTIME:-docker}"
checker="$(dirname "$0")/verify_image_apps.py"

# The checker arrives on stdin, so a dropped -i hands the interpreter an empty
# script and exits 0. An empty verdict is what that silent pass looks like.
verdict="$("$runtime" run --rm -i --entrypoint python "$image" - "$mode" < "$checker")"
if [ -z "$verdict" ]; then
    echo "$image: the checker produced no verdict, so it never ran" >&2
    exit 1
fi
echo "$verdict"
