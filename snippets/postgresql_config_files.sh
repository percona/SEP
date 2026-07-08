#!/usr/bin/env bash

# ---
# title: PostgreSQL Config File Collector
# description: Collects postgresql.conf and postgresql.auto.conf (plus any files referenced via include / include_if_exists / include_dir directives) into a tar.gz archive. Optionally masks values for sensitive parameters.
# allow_extra_args: false
# sudo: optional
# service_type: postgresql
# parameters:
#  - name: config-file
#    type: str
#    label: postgresql.conf path
#    description: Path to postgresql.conf. Auto-detected from psql or the running postgres process if omitted.
#    placeholder: /etc/postgresql/16/main/postgresql.conf
#  - name: auto-config-file
#    type: str
#    label: postgresql.auto.conf path
#    description: Path to postgresql.auto.conf. Defaults to the same directory as --config-file or the detected data_directory.
#    placeholder: /var/lib/postgresql/16/main/postgresql.auto.conf
#  - name: data-dir
#    type: str
#    label: PostgreSQL data directory
#    description: Override for the PostgreSQL data_directory (used to locate postgresql.auto.conf when --auto-config-file is not given).
#    placeholder: /var/lib/postgresql/16/main
#  - name: output
#    type: str
#    label: Output tar.gz path
#    description: Destination archive path. Defaults to postgresql_configs_<epoch>.tar.gz in the current directory.
#    placeholder: /tmp/postgresql_configs.tar.gz
#  - name: mask
#    type: bool
#    label: Mask sensitive values
#    description: Redact values for parameters whose names or contents look sensitive (password, passphrase, secret, primary_conninfo, archive_command, restore_command, ssl_passphrase_command).
#    default: false
#  - name: dbname
#    type: str
#    label: Target database
#    description: Database to connect to (psql --dbname). Defaults to postgres.
#    default: postgres
# atw:
#  - SERVER_CRASHED_RESTART_SUCCESSFUL
#  - SERVER_CRASHED_RESTART_NOT_SUCCESSFUL
# alerts:
#   - PostgreSQLIsDown
# ---

set -euo pipefail

CONFIG_FILE_ARG=""
AUTO_CONFIG_FILE_ARG=""
DATA_DIR_ARG=""
OUTPUT_ARG=""
DBNAME_ARG="${PGDATABASE:-postgres}"
MASK=0

usage() {
    local -i exit_code="${1:-0}"
    cat << EOS
Usage: $(basename "$0") [OPTIONS]

Collect postgresql.conf and postgresql.auto.conf into a tar.gz archive.

Options:
  --config-file <path>       Path to postgresql.conf (auto-detected if omitted).
  --auto-config-file <path>  Path to postgresql.auto.conf (defaults to data_directory).
  --data-dir <path>          PostgreSQL data directory override.
  --output <path>            Output tar.gz path (default: postgresql_configs_<epoch>.tar.gz).
  --dbname <db>              Target database for psql (default: postgres).
  --mask                     Redact values for sensitive parameters.
  -h, --help                 Show this help message.
EOS
    exit "${exit_code}"
}

if ! OPTS=$(getopt --options h --longoptions 'config-file:,auto-config-file:,data-dir:,output:,dbname:,mask,help' -- "$@"); then
    echo "Error parsing options" >&2
    usage 1
fi

eval set -- "$OPTS"

while [[ -n $* ]]; do
    case "$1" in
        --config-file)
            CONFIG_FILE_ARG="$2"
            shift 2
            ;;
        --auto-config-file)
            AUTO_CONFIG_FILE_ARG="$2"
            shift 2
            ;;
        --data-dir)
            DATA_DIR_ARG="$2"
            shift 2
            ;;
        --output)
            OUTPUT_ARG="$2"
            shift 2
            ;;
        --dbname)
            DBNAME_ARG="$2"
            shift 2
            ;;
        --mask)
            MASK=1
            shift
            ;;
        -h | --help) usage ;;
        --)
            shift
            break
            ;;
        *)
            echo "Unrecognized option '$1'" >&2
            usage 1
            ;;
    esac
done

export PGDATABASE="${DBNAME_ARG:-postgres}"

PSQL="psql"

# Auto-detect config_file and data_directory via psql, then via the running
# postgres process (-D <datadir>, --config-file=...), then via well-known
# distro layouts. Each fallback is independent so a partial detection still
# helps locate postgresql.auto.conf.
DATA_DIR=""
CONFIG_FILE=""

if [[ -n $CONFIG_FILE_ARG ]]; then
    CONFIG_FILE="$CONFIG_FILE_ARG"
fi
if [[ -n $DATA_DIR_ARG ]]; then
    DATA_DIR="$DATA_DIR_ARG"
fi

if [[ -z $CONFIG_FILE ]]; then
    detected=$($PSQL -tA -c "SELECT current_setting('config_file');" 2> /dev/null | xargs 2> /dev/null || true)
    if [[ -n $detected && -f $detected ]]; then
        CONFIG_FILE="$detected"
    fi
fi

if [[ -z $DATA_DIR ]]; then
    detected=$($PSQL -tA -c "SELECT current_setting('data_directory');" 2> /dev/null | xargs 2> /dev/null || true)
    if [[ -n $detected && -d $detected ]]; then
        DATA_DIR="$detected"
    fi
fi

if [[ -z $CONFIG_FILE || -z $DATA_DIR ]]; then
    POSTGRES_PID=""
    POSTGRES_CMD=""
    # Filter out this script's own PID — pgrep -af matches against the full
    # command line, and the script's filename contains "postgres".
    while IFS= read -r postgres_line; do
        POSTGRES_PID="${postgres_line%% *}"
        POSTGRES_CMD="${postgres_line#* }"
        if [[ $POSTGRES_PID =~ ^[0-9]+$ && -n $POSTGRES_CMD ]]; then
            break
        fi
        POSTGRES_PID=""
        POSTGRES_CMD=""
    done < <(pgrep -af 'postgres' 2> /dev/null | grep -v "^$$ " || true)
    if [[ -z $POSTGRES_PID ]]; then
        POSTGRES_PID=$(pgrep -x postmaster 2> /dev/null | head -1 || true)
        if [[ -n $POSTGRES_PID ]]; then
            POSTGRES_CMD=$(ps -p "$POSTGRES_PID" -o args= 2> /dev/null || true)
        fi
    fi
    if [[ -n $POSTGRES_PID && -n $POSTGRES_CMD ]]; then
        if [[ -z $DATA_DIR && $POSTGRES_CMD =~ -D[[:space:]]*([^[:space:]]+) ]]; then
            DATA_DIR="${BASH_REMATCH[1]}"
        fi
        if [[ -z $CONFIG_FILE && $POSTGRES_CMD =~ --config-file=([^[:space:]]+) ]]; then
            CONFIG_FILE="${BASH_REMATCH[1]}"
        fi
    fi
fi

if [[ -z $CONFIG_FILE ]]; then
    for candidate in \
        /etc/postgresql/*/main/postgresql.conf \
        /var/lib/pgsql/*/data/postgresql.conf \
        /var/lib/pgsql/data/postgresql.conf \
        /var/lib/postgresql/*/main/postgresql.conf; do
        if [[ -f $candidate ]]; then
            CONFIG_FILE="$candidate"
            break
        fi
    done
fi

if [[ -z $CONFIG_FILE ]]; then
    echo "Error: could not locate postgresql.conf. Pass --config-file." >&2
    exit 1
fi

if [[ ! -r "$CONFIG_FILE" ]] && ! sudo -n -u postgres test -r "$CONFIG_FILE" 2> /dev/null; then
    echo "Error: cannot read postgresql.conf at '$CONFIG_FILE' (check permissions or run with sudo)." >&2
    exit 1
fi

AUTO_CONFIG_FILE=""
if [[ -n $AUTO_CONFIG_FILE_ARG ]]; then
    AUTO_CONFIG_FILE="$AUTO_CONFIG_FILE_ARG"
elif [[ -n $DATA_DIR ]] && ([[ -r "$DATA_DIR/postgresql.auto.conf" ]] || sudo -n -u postgres test -r "$DATA_DIR/postgresql.auto.conf" 2> /dev/null); then
    AUTO_CONFIG_FILE="$DATA_DIR/postgresql.auto.conf"
else
    candidate="$(dirname "$CONFIG_FILE")/postgresql.auto.conf"
    if [[ -r "$candidate" ]] || sudo -n -u postgres test -r "$candidate" 2> /dev/null; then
        AUTO_CONFIG_FILE="$candidate"
    fi
fi

echo "postgresql.conf:      $CONFIG_FILE" >&2
echo "postgresql.auto.conf: ${AUTO_CONFIG_FILE:-<not found>}" >&2
echo "data_directory:       ${DATA_DIR:-<unknown>}" >&2

# Pull in any files brought in by include / include_if_exists / include_dir
# directives. Without them the captured bundle would not reflect the effective
# configuration. Relative paths resolve against the directive file's directory.
declare -A SEEN_FILES=()
EXTRA_FILES=()

resolve_path() {
    local base_dir="$1" raw="$2"
    raw="${raw#"${raw%%[![:space:]]*}"}"
    raw="${raw%"${raw##*[![:space:]]}"}"
    raw="${raw%\'}"
    raw="${raw#\'}"
    raw="${raw%\"}"
    raw="${raw#\"}"
    if [[ $raw == /* ]]; then
        echo "$raw"
    else
        echo "${base_dir}/${raw}"
    fi
}

walk_includes() {
    local file="$1"
    if [[ -z $file || ! -f $file ]]; then
        return
    fi
    local abs
    abs=$(readlink -f "$file" 2> /dev/null || echo "$file")
    if [[ -n ${SEEN_FILES[$abs]:-} ]]; then
        return
    fi
    SEEN_FILES[$abs]=1
    local base_dir
    base_dir=$(dirname "$abs")

    local line raw_value resolved
    if [[ -r $abs ]]; then
        while IFS= read -r line; do
            line="${line%%#*}"
            line="${line## }"
            # PostgreSQL accepts both `include = 'file'` and `include 'file'` (the
            # `=` is optional for include directives). Check the longer keywords
            # first so the plain `include` branch does not shadow include_dir or
            # include_if_exists.
            if [[ $line =~ ^[[:space:]]*include_if_exists[[:space:]]*=?[[:space:]]*(.+)$ ]]; then
                raw_value="${BASH_REMATCH[1]}"
                resolved=$(resolve_path "$base_dir" "$raw_value")
                if [[ -f $resolved ]]; then
                    EXTRA_FILES+=("$resolved")
                    walk_includes "$resolved"
                fi
            elif [[ $line =~ ^[[:space:]]*include_dir[[:space:]]*=?[[:space:]]*(.+)$ ]]; then
                raw_value="${BASH_REMATCH[1]}"
                resolved=$(resolve_path "$base_dir" "$raw_value")
                if [[ -d $resolved ]]; then
                    shopt -s nullglob
                    local incf
                    for incf in "$resolved"/*.conf; do
                        EXTRA_FILES+=("$incf")
                        walk_includes "$incf"
                    done
                    shopt -u nullglob
                fi
            elif [[ $line =~ ^[[:space:]]*include[[:space:]]*=?[[:space:]]*(.+)$ ]]; then
                raw_value="${BASH_REMATCH[1]}"
                resolved=$(resolve_path "$base_dir" "$raw_value")
                if [[ -f $resolved ]]; then
                    EXTRA_FILES+=("$resolved")
                    walk_includes "$resolved"
                fi
            fi
        done < "$abs"
    elif sudo -n -u postgres test -r "$abs" 2> /dev/null; then
        while IFS= read -r line; do
            line="${line%%#*}"
            line="${line## }"
            # PostgreSQL accepts both `include = 'file'` and `include 'file'` (the
            # `=` is optional for include directives). Check the longer keywords
            # first so the plain `include` branch does not shadow include_dir or
            # include_if_exists.
            if [[ $line =~ ^[[:space:]]*include_if_exists[[:space:]]*=?[[:space:]]*(.+)$ ]]; then
                raw_value="${BASH_REMATCH[1]}"
                resolved=$(resolve_path "$base_dir" "$raw_value")
                if [[ -f $resolved ]]; then
                    EXTRA_FILES+=("$resolved")
                    walk_includes "$resolved"
                fi
            elif [[ $line =~ ^[[:space:]]*include_dir[[:space:]]*=?[[:space:]]*(.+)$ ]]; then
                raw_value="${BASH_REMATCH[1]}"
                resolved=$(resolve_path "$base_dir" "$raw_value")
                if [[ -d $resolved ]]; then
                    shopt -s nullglob
                    local incf
                    for incf in "$resolved"/*.conf; do
                        EXTRA_FILES+=("$incf")
                        walk_includes "$incf"
                    done
                    shopt -u nullglob
                fi
            elif [[ $line =~ ^[[:space:]]*include[[:space:]]*=?[[:space:]]*(.+)$ ]]; then
                raw_value="${BASH_REMATCH[1]}"
                resolved=$(resolve_path "$base_dir" "$raw_value")
                if [[ -f $resolved ]]; then
                    EXTRA_FILES+=("$resolved")
                    walk_includes "$resolved"
                fi
            fi
        done < <(sudo -n -u postgres cat "$abs" 2> /dev/null || true)
    fi
}

walk_includes "$CONFIG_FILE"
if [[ -n $AUTO_CONFIG_FILE ]]; then
    walk_includes "$AUTO_CONFIG_FILE"
fi

# Sensitive parameter list — names whose values are redacted under --mask.
# Matched case-insensitively against the parameter name (before the = sign).
SENSITIVE_PATTERN='(password|passphrase|secret|primary_conninfo|archive_command|restore_command|ssl_passphrase_command)'

mask_file() {
    local src="$1" dst="$2"
    awk -v pat="$SENSITIVE_PATTERN" '
    {
        line = $0
        # Strip optional comment for parameter detection, but keep the trailing
        # comment intact when reassembling the line.
        if (match(line, /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/)) {
            name = substr(line, RSTART, RLENGTH - 1)
            sub(/[[:space:]]*$/, "", name)
            sub(/^[[:space:]]+/, "", name)
            lower = tolower(name)
            if (lower ~ pat) {
                print name " = ***REDACTED***"
                next
            }
        }
        print line
    }
    ' "$src" > "$dst"
}

# Stage everything in a temp dir so the tar layout is predictable (top-level
# directory equals the archive basename minus extension), and so masking does
# not touch the originals.
TMPDIR_STAGE=$(mktemp -d)
trap 'rm -rf "$TMPDIR_STAGE"' EXIT

if [[ -z $OUTPUT_ARG ]]; then
    OUTPUT_ARG="postgresql_configs_$(date +%s).tar.gz"
fi
STAGE_DIRNAME=$(basename "$OUTPUT_ARG")
STAGE_DIRNAME="${STAGE_DIRNAME%.tar.gz}"
STAGE_DIRNAME="${STAGE_DIRNAME%.tgz}"
STAGE_DIRNAME="${STAGE_DIRNAME%.tar}"
STAGE_DIR="$TMPDIR_STAGE/$STAGE_DIRNAME"
mkdir -p "$STAGE_DIR"
USE_SUDO_TAR=0

copy_into_stage() {
    local src="$1"
    local elevated="${2:-}"
    local src_abs
    if [[ -n $elevated ]]; then
        src_abs=$(sudo -n readlink -f "$src" 2> /dev/null || readlink -f "$src" 2> /dev/null || echo "$src")
        USE_SUDO_TAR=1
    else
        src_abs=$(readlink -f "$src" 2> /dev/null || echo "$src")
    fi
    if [[ $src_abs != /* ]]; then
        echo "Warning: refusing to stage non-absolute path '$src'" >&2
        return
    fi
    local rel
    # Preserve directory layout under the stage dir so multiple files with the
    # same basename (e.g. several included *.conf shards) don't collide. The
    # absolute-path guard above is what prevents traversal; readlink -f
    # canonicalizes duplicate slashes so ${src_abs#/} can't re-introduce one.
    rel="${src_abs#/}"
    local dst="$STAGE_DIR/$rel"
    mkdir -p "$(dirname "$dst")"
    if [[ $MASK -eq 1 ]]; then
        if [[ -n $elevated ]]; then
            sudo -n cat "$src_abs" | awk -v pat="$SENSITIVE_PATTERN" '
            {
                line = $0
                if (match(line, /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/)) {
                    name = substr(line, RSTART, RLENGTH - 1)
                    sub(/[[:space:]]*$/, "", name)
                    sub(/^[[:space:]]+/, "", name)
                    lower = tolower(name)
                    if (lower ~ pat) {
                        print name " = ***REDACTED***"
                        next
                    }
                }
                print line
            }
            ' > "$dst"
        else
            mask_file "$src_abs" "$dst"
        fi
    elif [[ -n $elevated ]]; then
        sudo -n cp "$src_abs" "$dst"
    else
        cp "$src_abs" "$dst"
    fi
}

if [[ ! -r "$CONFIG_FILE" ]]; then
    copy_into_stage "$CONFIG_FILE" sudo
else
    copy_into_stage "$CONFIG_FILE"
fi
if [[ -n $AUTO_CONFIG_FILE ]]; then
    if [[ -r "$AUTO_CONFIG_FILE" ]]; then
        copy_into_stage "$AUTO_CONFIG_FILE"
    else
        copy_into_stage "$AUTO_CONFIG_FILE" sudo
    fi
fi

declare -A COPIED=()
COPIED["$(readlink -f "$CONFIG_FILE")"]=1
if [[ -n $AUTO_CONFIG_FILE ]]; then
    COPIED["$(sudo -n readlink -f "$AUTO_CONFIG_FILE" 2> /dev/null || readlink -f "$AUTO_CONFIG_FILE" 2> /dev/null || echo "$AUTO_CONFIG_FILE")"]=1
fi
for extra in "${EXTRA_FILES[@]+"${EXTRA_FILES[@]}"}"; do
    abs=$(readlink -f "$extra" 2> /dev/null || echo "$extra")
    if [[ -n ${COPIED[$abs]:-} ]]; then
        continue
    fi
    COPIED[$abs]=1
    if [[ -r "$extra" ]]; then
        copy_into_stage "$extra"
    elif sudo -n -u postgres test -r "$extra" 2> /dev/null; then
        copy_into_stage "$extra" sudo
    fi
done

# A small manifest helps the support engineer see where each file came from
# and whether masking was applied.
{
    echo "Generated:        $(date -Iseconds)"
    echo "Host:             $(hostname)"
    echo "postgresql.conf:  $CONFIG_FILE"
    echo "postgresql.auto.conf: ${AUTO_CONFIG_FILE:-<not found>}"
    echo "data_directory:   ${DATA_DIR:-<unknown>}"
    echo "Masked:           $([[ $MASK -eq 1 ]] && echo yes || echo no)"
    echo
    echo "Included files:"
    for k in "${!COPIED[@]}"; do
        echo "  $k"
    done | sort
} > "$STAGE_DIR/MANIFEST.txt"

if [[ $USE_SUDO_TAR -eq 1 ]]; then
    sudo -n tar -czf - -C "$TMPDIR_STAGE" "$STAGE_DIRNAME" > "$OUTPUT_ARG"
else
    tar -czf "$OUTPUT_ARG" -C "$TMPDIR_STAGE" "$STAGE_DIRNAME"
fi

echo "Archive written to: $OUTPUT_ARG" >&2
echo "Files included:     ${#COPIED[@]}" >&2
if [[ $MASK -eq 1 ]]; then
    echo "Masking:            ON (sensitive parameter values were redacted)" >&2
fi
