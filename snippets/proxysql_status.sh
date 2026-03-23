#!/usr/bin/env bash

# ---
# title: "ProxySQL Status"
# description: "Displays ProxySQL status information including tables and configuration files"
# allow_extra_args: false
# parameters:
#  - name: defaults-file
#    type: str
#    label: Config file
#    description: Path to ProxySQL admin config file
#    placeholder: /etc/proxysql-admin.cnf
#  - name: files
#    type: bool
#    label: Show files
#    description: Display contents of proxysql-admin related files
#    default: false
#  - name: main
#    type: bool
#    label: Main tables
#    description: Display main tables (both on-disk and runtime)
#    default: false
#  - name: monitor
#    type: bool
#    label: Monitor tables
#    description: Display monitor tables
#    default: false
#  - name: runtime
#    type: bool
#    label: Runtime data
#    description: Display runtime-related data (implies --main)
#    default: false
#  - name: stats
#    type: bool
#    label: Stats tables
#    description: Display stats tables
#    default: false
#  - name: output
#    type: str
#    description: Where to send the output
#    label: Output destination
#    default: stdout
#    choices:
#      - value: stdout
#        label: Print to the terminal (default)
#      - value: file
#        label: Write the output to a file named by the timestamp
# ---

declare DEFAULTS_FILE="/etc/proxysql-admin.cnf"
declare USER=""
declare PASSWORD=""
declare HOST=""
declare PORT=""
declare RUNTIME_OPTION=""
declare DUMP_ALL=1
declare DUMP_MAIN=0
declare DUMP_STATS=0
declare DUMP_MONITOR=0
declare DUMP_FILES=0
declare TABLE_FILTER=""
declare OUTPUT_MODE="stdout"
declare OUTPUT_FILE=""

function usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Options:
  --defaults-file <file> Config file (default: /etc/proxysql-admin.cnf)
  --files                Show config files
  --main                 Show main tables
  --monitor              Show monitor tables
  --runtime              Show runtime data
  --stats                Show stats tables
  --table <name>         Filter by table name
  --output <file|stdout> Output destination (default: stdout)
  --help                 Show this message
EOF
    exit 1
}

#
# Executes an SQL query
#
# Globals:
#   USER
#   PASSWORD
#   HOST
#   PORT
#
# Arguments:
#   1: arguments to be passed to mysql
#   2: the query
#
function mysql_exec() {
    local args=$1
    local query=$2
    local retvalue
    local retoutput

    retoutput=$(printf "[client]\nuser=%s\npassword=\"%s\"\nhost=%s\nport=%s" "${USER}" "${PASSWORD}" "${HOST}" "${PORT}" |
        mysql --defaults-file=/dev/stdin --protocol=tcp \
            ${args} -e "${query}" 2>&1 | grep -v "mylogin.cnf")
    retvalue=$?

    if [[ -n $retoutput ]]; then
        retoutput+=$'\n'
    fi
    printf "%s" "${retoutput//%/%%}"
    return $retvalue
}

function parse_args() {
    local go_out=""

    # TODO: kennt, what happens if we don't have a functional getopt()?
    # Check if we have a functional getopt(1)
    if ! getopt --test; then
        if ! go_out="$(getopt --options=h --longoptions=defaults-file:,runtime,main,stats,monitor,files,table::,output:,help \
            --name="$(basename "$0")" -- "$@")"; then
            # no place to send output
            echo "Script error: getopt() failed" >&2
            exit 1
        fi
        eval set -- "$go_out"
    fi

    for arg; do
        case "$arg" in
            --)
                shift
                break
                ;;
            --defaults-file)
                if [[ -z $2 || $2 == --* ]]; then
                    echo "Error: --defaults-file requires an argument."
                    usage
                fi
                DEFAULTS_FILE=$2
                shift 2
                ;;
            --runtime)
                shift
                RUNTIME_OPTION=" LIKE 'runtime_%'"
                DUMP_ALL=0
                DUMP_MAIN=1
                ;;
            --main)
                shift
                DUMP_ALL=0
                DUMP_MAIN=1
                ;;
            --stats)
                shift
                DUMP_ALL=0
                DUMP_STATS=1
                ;;
            --monitor)
                shift
                DUMP_ALL=0
                DUMP_MONITOR=1
                ;;
            --files)
                shift
                DUMP_ALL=0
                DUMP_FILES=1
                ;;
            --table)
                if [[ -z $2 || $2 == --* ]]; then
                    echo "Error: --table requires an argument."
                    usage
                fi
                TABLE_FILTER=$2
                shift 2
                ;;
            --output)
                if [[ -z $2 || $2 == --* ]]; then
                    echo "Error: --output requires an argument (file|stdout)."
                    usage
                fi
                OUTPUT_MODE=$2
                shift 2
                ;;
            -h | --help)
                usage
                ;;
        esac
    done

    if [[ ! -r $DEFAULTS_FILE ]]; then
        echo "Cannot find or read $DEFAULTS_FILE."
        exit 1
    fi

    # Load credentials from config file
    # shellcheck disable=SC1090
    source "$DEFAULTS_FILE"
    USER=${PROXYSQL_USERNAME:-}
    PASSWORD=${PROXYSQL_PASSWORD:-}
    HOST=${PROXYSQL_HOSTNAME:-127.0.0.1}
    PORT=${PROXYSQL_PORT:-6032}

    # Validate output mode
    if [[ $OUTPUT_MODE != "stdout" && $OUTPUT_MODE != "file" ]]; then
        echo "Error: --output must be either 'stdout' or 'file'."
        usage
    fi

    # If output is file, create filename with timestamp
    if [[ $OUTPUT_MODE == "file" ]]; then
        OUTPUT_FILE="proxysql_status_$(date +%s).log"
    fi
}

parse_args "$@"

# Function to execute the main script logic
function run_dumps() {
    if [[ $DUMP_ALL -eq 1 || $DUMP_MAIN -eq 1 ]]; then
        echo "............ DUMPING MAIN DATABASE ............"
        TABLES=$(mysql_exec -BN "SHOW TABLES $RUNTIME_OPTION" 2> /dev/null)
        for table in $TABLES; do
            if [[ -n $TABLE_FILTER && $table != *${TABLE_FILTER}* ]]; then
                continue
            fi
            echo "***** DUMPING $table *****"
            mysql_exec -t "SELECT * FROM $table"
            echo "***** END OF DUMPING $table *****"
            echo ""
        done
        echo "............ END OF DUMPING MAIN DATABASE ............"
        echo ""
    fi

    if [[ $DUMP_ALL -eq 1 || $DUMP_STATS -eq 1 ]]; then
        echo "............ DUMPING STATS DATABASE ............"
        TABLES=$(mysql_exec -BN "SHOW TABLES FROM stats" 2> /dev/null)
        for table in $TABLES; do
            if [[ -n $TABLE_FILTER && $table != *${TABLE_FILTER}* ]]; then
                continue
            fi
            echo "***** DUMPING stats.$table *****"
            mysql_exec "-t --database=stats" "SELECT * FROM $table" 2> /dev/null
            echo "***** END OF DUMPING stats.$table *****"
            echo ""
        done
        echo "............ END OF DUMPING STATS DATABASE ............"
        echo ""
    fi

    if [[ $DUMP_ALL -eq 1 || $DUMP_MONITOR -eq 1 ]]; then
        echo "............ DUMPING MONITOR DATABASE ............"
        TABLES=$(mysql_exec -BN "SHOW TABLES FROM monitor" 2> /dev/null)
        for table in $TABLES; do
            if [[ -n $TABLE_FILTER && $table != *${TABLE_FILTER}* ]]; then
                continue
            fi
            echo "***** DUMPING monitor.$table *****"
            mysql_exec "-t --database=monitor" "SELECT * FROM $table" 2> /dev/null
            echo "***** END OF DUMPING monitor.$table *****"
            echo ""
        done
        echo "............ END OF DUMPING MONITOR DATABASE ............"
        echo ""
    fi

    if [[ $DUMP_ALL -eq 1 || $DUMP_FILES -eq 1 ]]; then
        if [[ -z $TABLE_FILTER ]]; then
            DATADIR=$(mysql_exec -BN "SELECT variable_value FROM global_variables WHERE variable_name='admin-datadir'" 2> /dev/null)
            if [[ -z $DATADIR ]]; then
                DATADIR="/var/lib/proxysql"
            fi

            HOST_PRIORITY_CONTENT=$(cat "${DATADIR}/host_priority.conf" 2> /dev/null)
            if [[ -n $HOST_PRIORITY_CONTENT ]]; then
                echo "............ DUMPING HOST PRIORITY FILE ............"
                echo "$HOST_PRIORITY_CONTENT"
                echo "............ END OF DUMPING HOST PRIORITY FILE ............"
                echo ""
            fi

            ADMIN_CNF_CONTENT=$(cat "$DEFAULTS_FILE" 2> /dev/null)
            if [[ -n $ADMIN_CNF_CONTENT ]]; then
                echo "............ DUMPING PROXYSQL ADMIN CNF FILE ............"
                echo "$ADMIN_CNF_CONTENT"
                echo "............ END OF DUMPING PROXYSQL ADMIN CNF FILE ............"
                echo ""
            fi
        fi
    fi
}

if [[ $OUTPUT_MODE == "file" ]]; then
    run_dumps > "$OUTPUT_FILE" 2>&1
    echo "Output written to $OUTPUT_FILE"
else
    run_dumps
fi
