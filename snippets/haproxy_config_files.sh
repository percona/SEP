#!/usr/bin/env bash

# ---
# title: HAProxy Config File Discovery Script
# description: This script finds all HAProxy config files, including those referenced by include directives and conf.d directories, and displays their contents along with version and service status.
# allow_extra_args: false
# sudo: optional
# service_type: haproxy
# parameters: []
# ---

set -e

# Track processed files to avoid infinite loops
declare -A PROCESSED_FILES

process_config_file() {
    local file="$1"
    if [[ -n ${PROCESSED_FILES["$file"]} ]]; then
        return
    fi
    PROCESSED_FILES["$file"]=1

    if [ -f "$file" ]; then
        echo
        echo "---- Found: $file ----"
        ls -l "$file"
        echo
        # Degrade gracefully on unreadable files instead of aborting under `set -e`
        # (e.g. when run without sudo). Skip contents and includes we cannot read.
        if [ ! -r "$file" ]; then
            echo "(not readable; skipping contents - try running with sudo)"
            echo "----------------------"
            return
        fi
        cat "$file"
        echo "----------------------"
        # Parse for HAProxy native include directives (supported since 2.4)
        while IFS= read -r line; do
            line="${line#"${line%%[![:space:]]*}"}"
            line="${line%"${line##*[![:space:]]}"}"
            # Strip inline comments and skip empty/comment-only lines.
            line="${line%%#*}"
            line="${line#"${line%%[![:space:]]*}"}"
            line="${line%"${line##*[![:space:]]}"}"
            [[ -z $line ]] && continue
            if [[ $line =~ ^include[[:space:]]+(.+) ]]; then
                included_glob="${BASH_REMATCH[1]}"
                # HAProxy `include` supports glob patterns; expand the glob without evaluating it as shell code.
                while IFS= read -r included_file; do
                    process_config_file "$included_file"
                done < <(compgen -G "$included_glob" || true)
            fi
        done < "$file"
    fi
}

echo "=== HAProxy Config File Discovery Script ==="
echo

# List of common HAProxy config file locations
COMMON_PATHS=(
    "/etc/haproxy/haproxy.cfg"
    "/etc/haproxy/haproxy.conf"
    "/usr/local/etc/haproxy/haproxy.cfg"
    "/usr/local/etc/haproxy/haproxy.conf"
    "/opt/haproxy/etc/haproxy.cfg"
)

# Scan common HAProxy config directories (conf.d pattern used by most distro packages)
echo "Checking common HAProxy config directories..."
HAPROXY_DIRS=(
    "/etc/haproxy"
    "/etc/haproxy/conf.d"
    "/usr/local/etc/haproxy"
    "/usr/local/etc/haproxy/conf.d"
)

for haproxy_dir in "${HAPROXY_DIRS[@]}"; do
    if [ -d "$haproxy_dir" ]; then
        for conf_file in "$haproxy_dir"/*.cfg "$haproxy_dir"/*.conf; do
            [ -e "$conf_file" ] && COMMON_PATHS+=("$conf_file")
        done
    fi
done

# Remove duplicates
readarray -t UNIQUE_PATHS < <(printf "%s\n" "${COMMON_PATHS[@]}" | sort -u)

echo "=== Checking HAProxy config file locations (and their includes) ==="
for path in "${UNIQUE_PATHS[@]}"; do
    process_config_file "$path"
done

echo
echo "=== HAProxy Version ==="
if command -v haproxy &> /dev/null; then
    haproxy -v
else
    echo "haproxy binary not found in PATH"
fi

echo
echo "=== HAProxy Service Status ==="
if command -v systemctl &> /dev/null; then
    systemctl status haproxy --no-pager 2> /dev/null || echo "haproxy service not found or not running"
else
    echo "systemctl not available"
fi

echo
echo "=== Done ==="
