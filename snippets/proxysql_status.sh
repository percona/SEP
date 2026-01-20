#!/bin/bash -u

# ---
# title: "ProxySQL Status"
# description: "Displays ProxySQL status information including tables and configuration files"
# allow_extra_args: false
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to ProxySQL admin config file
#    description: Path to the config file containing ProxySQL admin credentials
#    default: "/etc/proxysql-admin.cnf"
#  - name: files
#    type: int
#    label: Display contents of proxysql-admin related files
#    description: Display contents of proxysql-admin related files
#    default: 0
#  - name: main
#    type: int
#    label: Display main tables
#    description: Display main tables (both on-disk and runtime)
#    default: 0
#  - name: monitor
#    type: int
#    label: Display monitor tables
#    description: Display monitor tables
#    default: 0
#  - name: runtime
#    type: int
#    label: Display runtime-related data
#    description: Display runtime-related data (implies --main)
#    default: 0
#  - name: stats
#    type: int
#    label: Display stats tables
#    description: Display stats tables
#    default: 0
#  - name: table
#    type: str
#    label: Filter by table name
#    description: Display only tables that contain the table name (case-sensitive)
#    default: ""
#  - name: help
#    type: int
#    label: Show help message
#    description: Show help message
#    default: 0
# ---


function usage() {
    echo "Usage: $0 [--defaults-file <file>] [--files] [--main] [--monitor] [--runtime] [--stats] [--table <table_name>] [--help]"
    echo "Example: $0 --files"
    echo "         $0 --main --table mysql_servers"
    echo "         $0 --defaults-file /path/to/config.cnf --stats"
    echo ""
    echo "This script displays ProxySQL status information including tables and configuration files."
    echo "By default, it displays all tables and files."
    echo ""
    echo "Arguments:"
    echo "  --defaults-file <file>             Optional. Path to ProxySQL admin config file. Defaults to /etc/proxysql-admin.cnf."
    echo "  --files                           Display contents of proxysql-admin related files."
    echo "  --main                            Display main tables (both on-disk and runtime)."
    echo "  --monitor                         Display monitor tables."
    echo "  --runtime                         Display runtime-related data (implies --main)."
    echo "  --stats                           Display stats tables."
    echo "  --table <table_name>              Display only tables that contain the table name (case-sensitive)."
    echo "  --help                            Show this help message."
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

  retoutput=$(printf "[client]\nuser=${USER}\npassword=\"${PASSWORD}\"\nhost=${HOST}\nport=${PORT}"  \
      | mysql --defaults-file=/dev/stdin --protocol=tcp \
            ${args} -e "${query}")
  retvalue=$?

  if [[ -n $retoutput ]]; then
    retoutput+="\n"
  fi
  printf "${retoutput//%/%%}"
  return $retvalue
}


declare USER
declare PASSWORD
declare HOST
declare PORT
declare DEFAULTS_FILE="/etc/proxysql-admin.cnf"
declare RUNTIME_OPTION=""
declare DUMP_ALL=1
declare DUMP_MAIN=0
declare DUMP_STATS=0
declare DUMP_MONITOR=0
declare DUMP_FILES=0
declare TABLE_FILTER=""


function parse_args() {
    local go_out=""

   # TODO: kennt, what happens if we don't have a functional getopt()?
    # Check if we have a functional getopt(1)
    if ! getopt --test; then
        go_out="$(getopt --options=h --longoptions=defaults-file:,runtime,main,stats,monitor,files,table:,help \
        --name="$(basename "$0")" -- "$@")"
        if [[ $? -ne 0 ]]; then
            # no place to send output
            echo "Script error: getopt() failed" >&2
            exit 1
        fi
        eval set -- "$go_out"
    fi

    for arg
    do
        case "$arg" in
            -- ) shift; break;;
            --defaults-file )
                if [[ -z "$2" || "$2" == --* ]]; then
                    echo "Error: --defaults-file requires an argument."
                    usage
                fi
                DEFAULTS_FILE=$2
                shift 2
                ;;
            --runtime )
                shift
                RUNTIME_OPTION=" LIKE 'runtime_%'"
                DUMP_ALL=0
                DUMP_MAIN=1
                ;;
            --main )
                shift
                DUMP_ALL=0
                DUMP_MAIN=1
                ;;
            --stats )
                shift
                DUMP_ALL=0
                DUMP_STATS=1
                ;;
            --monitor )
                shift
                DUMP_ALL=0
                DUMP_MONITOR=1
                ;;
            --files )
                shift
                DUMP_ALL=0
                DUMP_FILES=1
                ;;
            --table )
                if [[ -z "$2" || "$2" == --* ]]; then
                    echo "Error: --table requires an argument."
                    usage
                fi
                TABLE_FILTER=$2
                shift 2
                ;;
            -h | --help )
                usage
                exit 1
                break;;
        esac
    done

    if [[ ! -r $DEFAULTS_FILE ]]; then
        echo "Cannot find or read $DEFAULTS_FILE."
        exit 1
    fi
    source $DEFAULTS_FILE
    USER=$PROXYSQL_USERNAME
    PASSWORD=$PROXYSQL_PASSWORD
    HOST=$PROXYSQL_HOSTNAME
    PORT=$PROXYSQL_PORT
}


parse_args "$@"

if [[ $DUMP_ALL -eq 1 || $DUMP_MAIN -eq 1 ]]; then
    echo "............ DUMPING MAIN DATABASE ............"
    TABLES=$(mysql_exec -BN "SHOW TABLES $RUNTIME_OPTION" 2>/dev/null)
    for table in $TABLES
    do
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
    for table in $TABLES
    do
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
    for table in $TABLES
    do
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
        echo "............ DUMPING HOST PRIORITY FILE ............"
        cat /var/lib/proxysql/host_priority.conf 2>&1
        echo "............ END OF DUMPING HOST PRIORITY FILE ............"
        echo ""

        echo "............ DUMPING PROXYSQL ADMIN CNF FILE ............"
        cat /etc/proxysql-admin.cnf 2>&1
        echo "............ END OF DUMPING PROXYSQL ADMIN CNF FILE ............"
        echo ""
    fi
fi
