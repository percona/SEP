#!/bin/bash
#
# ---
# title: Collect Environment (MySQL)
# description: Collect diagnostic environment data for a MySQL host and store results in an archive.
# parameters:
#   - name: o
#     label: DB CLI options
#     description: Additional arguments passed to the MySQL CLI (e.g. "-h 127.0.0.1 -u user").
#     arg_format: "-o ${value}"
#   - name: d
#     label: Output suffix
#     description: Additional string to add after hostname in the output name.
#     arg_format: "-d ${value}"
#   - name: i
#     label: RDS hostname
#     description: Skip non-DB data collection (CPU/Disk/Memory). Intended for DBaaS/RDS. Provide hostname.
#     arg_format: "-i ${value}"
#   - name: t
#     label: Skip tar
#     description: Do not create a tar archive after the collection finishes.
#     type: bool
#     arg_format: "-t"
#   - name: r
#     label: Run without root
#     description: Run without root privileges (may cause permission denied errors).
#     type: bool
#     arg_format: "-r"
#   - name: p
#     label: DB PID
#     description: Use this specific PID when multiple instances are running.
#     type: int
#     arg_format: "-p ${value}"
#   - name: n
#     label: Max table count
#     description: Skip most schema collection if more than this many tables (0 disables the check).
#     type: int
#     arg_format: "-n ${value}"
# ---

## Globals
PT_DIRECTORY=".percona-toolkit"
DB_CLI_OPTIONS=()
OUT_DIR=$(hostname)_environment_$(date +%FT%H%M)
if [[ -z ${ISRDS} ]]; then
    ISRDS=0
fi
PIDTOUSE=""
RUNASROOT=1
SKIPROOTCHECK=0
SKIPTARRESULT=0

## DB Globals
MYSQLBASEDIR=${MYSQLBASEDIR:-/usr/bin}
NUMBER_OF_TABLES=10000
SKIP_SYS_TABLES=(innodb_buffer_stats_by_schema innodb_buffer_stats_by_table schema_object_overview schema_table_statistics_with_buffer)
TOO_MANY_TABLES=0
PT_TOOLS=(pt-align pt-config-diff pt-duplicate-key-checker pt-summary pt-mysql-summary)

## Parse arguments
function usage {
    cat << EOF
 Percona Consulting Scripts - v1.3.0
 Usage: $0 [-h] [-o DB arguments] [-d additional string] [-i RDS hostname] [-t] [-r] [-p pid] [-n number of tables]


 GLOBAL OPTIONS:
    -h        Show this message
    -o string Additional arguments to DB CLI (Ex: "-h hostname -u username")
    -d string Additional string add after hostname in output tarball
    -i string Does not collect non-DB related information (for example: disk, mem, cpu). Used in DBaaS like RDS.
              Specify hostname as argument.
    -t        Do not tar the directory after collection is finished
    -r        Run without root privileges (will get permission denied errors)
    -p int    Use this specific PID for DB when multiple instances are running

 MySQL OPTIONS:
    -n int    Skip collection of most schema-related info if more than this many tables (Default: 1000, Disable: 0)


EOF
}

while getopts hrto:d:i:p:n: flag; do
    case ${flag} in
        o)
            IFS=" " read -r -a OPTS <<< "${OPTARG}"
            for o in "${OPTS[@]}"; do
                DB_CLI_OPTIONS+=("${o}")
            done
            ;;
        d)
            OUTDIRADD="${OPTARG}_"
            OUT_DIR="$(hostname)_${OUTDIRADD}environment_"$(date +%FT%H%M)
            ;;
        i)
            echo "** Will not collect CPU/Disk/Memory stats **"
            ISRDS=1
            OUT_DIR="${OPTARG}_${OPTARG}environment_"$(date +%FT%H%M)
            ;;
        t)
            SKIPTARRESULT=1
            ;;
        r)
            SKIPROOTCHECK=1
            ;;
        p)
            PIDTOUSE="${OPTARG}"
            ;;
        h)
            usage
            exit 0
            ;;
        n)
            NUMBER_OF_TABLES="${OPTARG}"
            ;;
        *)
            usage
            exit 1
            ;;
    esac
done

shift $((OPTIND - 1))

## Functions

# Download pt tools if we cannot find them
function check_percona_toolkit {
    mkdir -p "${PT_DIRECTORY}"

    echo "Downloading percona toolkit tools, Check http://www.percona.com/software/percona-toolkit for more details"
    GETBIN=""
    if check_binary wget; then
        GETBIN=(wget --no-verbose -O "${PT_DIRECTORY}")
    elif check_binary curl; then
        GETBIN=(curl -sS -o "${PT_DIRECTORY}")
    else
        echo "Unable to find curl or wget to download tools."
        exit 1
    fi

    echo "Using '${GETBIN[*]}/' to download Percona Toolkit tools"

    # shellcheck disable=SC2043  # Ignore single iteration warning
    for TOOL in pt-align pt-config-diff pt-duplicate-key-checker pt-summary pt-mysql-summary; do
        if test -f "${PT_DIRECTORY}/${TOOL}"; then
            echo "-- Found ${PT_DIRECTORY}/${TOOL}"
        else
            echo "-- Downloading ${TOOL}..."
            # shellcheck disable=SC2086  # Ignore array expansion warning
            ${GETBIN[*]}/"${TOOL}" "https://www.percona.com/get/${TOOL}"
        fi
    done

    if [[ ! -f "${PT_DIRECTORY}/${PT_TOOLS[0]}" ]]; then
        echo "Could not download toolkit tools. Please manually download from http://www.percona.com/downloads/percona-toolkit/ and untar"
        exit 1
    fi
    chmod +x "${PT_DIRECTORY}"/pt-*
}

function check_perl_module {
    local module=$1
    if ! perl "-M${module}" -e 1 2> /dev/null; then
        echo "Missing Perl ${module}"
        echo "Typical install via apt|yum install perl-Data-Dumper perl-Digest-MD5 perl-DBD-MySQL"
        echo "You may also need: perl-English perl-Sys-Hostname perl-FindBin"
        exit 1
    fi
}

# Print error if specified binary not found.
# @param  Binary.
# Example: check_binary numactl
function check_binary {
    local binary=$1
    if ! which "${binary}" &> /dev/null; then
        echo -e "\nWARNING: Could not find ${binary} in '${PATH}', or it is not executable."
        return 1
    else
        return 0
    fi
}

# Check if more than 1 pid for database
# @param process name
# @param database name
function check_pids {
    local dbname=$1
    shift
    local daemon=("$@")

    set +e
    IFS=" " read -r -a pids <<< "$(pidof "${daemon[@]}")"
    set -e
    numPids=${#pids[@]}

    if [[ ${numPids} -eq 1 ]]; then
        PIDTOUSE="${pids[0]}"
    elif [[ ${numPids} -gt 1 ]] && [[ -z ${PIDTOUSE} ]]; then
        echo "Problem:"
        echo " Found ${#pids[@]} (${pids[*]}) pids for ${dbname}. Are there multiple instances of ${dbname} running?"
        echo " You need to specify which PID to use by passing '-p <pid>'"
        exit 1
    elif [[ ${numPids} -eq 0 ]]; then
        echo "Problem:"
        echo "Could not find a ${dbname} PID"
        exit 1
    fi
}

## Db Functions
# Try to run a query and print error if it fails.
function check_mysql_connection {
    local result
    result=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -NBe 'SELECT 1' 2> /dev/null)
    if [[ ${result} != "1" ]]; then
        echo "Can't connect to local mysql using '${MYSQLBASEDIR}/mysql'. Please add connection information to ~/.my.cnf"
        echo "Example: "
        echo "[client]"
        echo "user=percona"
        echo "password=s3cret"
        echo "# If RDS, add host="
        echo ""
        exit 1
    fi
}

# Check if there are many tables on the server.
# TOO_MANY_TABLES = (tables in server > $NUMBER_OF_TABLES)
function check_number_of_tables {
    local table_num=0
    if [[ ${NUMBER_OF_TABLES} -gt 0 ]]; then
        for db in $("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -BN -e "show databases" 2> /dev/null | grep -vE '^information_schema$|^performance_schema$|^mysql$|^sys$'); do
            table_num=$((table_num + $("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -BN -e "use \`${db}\`; show tables" 2> /dev/null | wc -l)))
            if [[ ${table_num} -gt ${NUMBER_OF_TABLES} ]]; then
                TOO_MANY_TABLES=1
                break
            fi
        done
    else
        echo -e "\nWARNING: Skipping number of tables check"
    fi
    echo "${table_num}" > "${OUT_DIR}/number_of_tables"
}

# Execute an SQL string and write output into a text file
# @param  description, printed to stdout
# @param  sql query
# @param  new file name
# @param  align output
# Example:
# sql_to_file 'Useless list of collations' 'SHOW COLLATIONS' 'collations'
function sql_to_file {
    local stat_desc=$1
    local stat_query=$2
    local stat_file=$3
    local align=${4:-true}

    echo " - ${stat_desc}"
    echo "-----${stat_query}=====" > "${OUT_DIR}"/"${stat_file}"

    if [[ ${align} == "noalign" ]]; then
        "${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -e "${stat_query}" 2> /dev/null 1>> "${OUT_DIR}"/"${stat_file}"
    else
        "${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -e "${stat_query}" 2> /dev/null | "${PT_DIRECTORY}/pt-align" 2> /dev/null 1>> "${OUT_DIR}"/"${stat_file}"
    fi
}

# Test required perl modules
check_perl_module Data::Dumper # For pt-align
check_perl_module Digest::MD5  # For pt-duplicate-key-checker
check_perl_module DBI          # For pt-duplicate-key-checker
check_perl_module DBD::mysql   # For pt-duplicate-key-checker

## Global Pre-flight Checks

# Ensure output directory
mkdir -p "${OUT_DIR}"

# Start
date -u -Iseconds > "${OUT_DIR}/collect_env_start"

# Don't need to be root if RDS
if [[ ${ISRDS} -eq 0 ]] && [[ "$(whoami)" != "root" ]] && [[ ${SKIPROOTCHECK} -ne 1 ]]; then
    echo "ERROR: $0 must be run by root"
    exit 1
fi

# If not root, and skipping root check, don't run anything requiring root
if [[ "$(whoami)" != "root" ]] && [[ ${SKIPROOTCHECK} -eq 1 ]]; then
    RUNASROOT=0
fi

set -ue

# check if all tools are available
check_percona_toolkit

# Database connectivity check
check_mysql_connection

## Database Pre-flight checks

# Any checks that might prevent script should take place here. This is also the location
# to discover any global variables/settings from the DB which will be used later in the script.

# If not RDS, check for multiple PIDs
if [[ ${ISRDS} -eq 0 ]]; then
    daemons=(mysqld mariadbd)
    check_pids MySQL "${daemons[@]}"
fi

# get some MySQL variables we'll need
variables_datadir=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -NBe "SELECT @@global.datadir;" 2> /dev/null)
variables_tmpdir=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -NBe "SELECT @@global.tmpdir;" 2> /dev/null)
variables_log_error=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -NBe "SELECT @@global.log_error;" 2> /dev/null)
variables_innodb_open_files=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -NBe "SELECT @@global.innodb_open_files;" 2> /dev/null)
variables_open_files_limit=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -NBe "SELECT @@global.open_files_limit;" 2> /dev/null)
variables_innodb_stats_on_metadata=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -NBe "SELECT @@global.innodb_stats_on_metadata;" 2> /dev/null)

# Try to set innodb_stats_on_metadata=0. If we fail, abort the script.
if [[ ${variables_innodb_stats_on_metadata} -ne 0 ]]; then
    echo "!!! We will set global innodb_stats_on_metadata = 0. "
    echo "!!! If absolutely necessary, please set it back with mysql -e 'set global innodb_stats_on_metadata = 1'"

    # check if SET succeeded (do we have SUPER?)
    if ! message=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -e 'set global innodb_stats_on_metadata = 0' 2>&1); then
        echo "${message}"
        echo 'Could not set innodb_stats_on_metadata. Executing this script without this change would be dangerous. Stopping'
        exit 1
    fi
fi

# If innodb_open_files > open_files_limit abort.
# More info: https://bugs.launchpad.net/percona-server/+bug/1510564
if [[ ${variables_innodb_open_files} -gt ${variables_open_files_limit} ]]; then
    echo "innodb_open_files > open_files_limit. They are, respectively ${variables_innodb_open_files} and ${variables_open_files_limit}."
    echo "This can cause a crash. Fix the problem before running this script."
    exit 1
fi

# Always check the number of tables
check_number_of_tables

## Main

# Ignore errors and keep collecting
set +e

## System config

if [[ ${ISRDS} -eq 0 ]]; then

    ## Db Sysconfig Pre

    ## Main sysconfig
    echo "Collecting system info... "

    cat /proc/cpuinfo > "${OUT_DIR}/cpuinfo"
    cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > "${OUT_DIR}/scaling_governor" 2> /dev/null
    cpupower frequency-info > "${OUT_DIR}/cpupower_frequency-info" 2>&1
    cat /proc/meminfo > "${OUT_DIR}/meminfo"
    cat /proc/sys/vm/swappiness > "${OUT_DIR}/swappiness"
    "${PT_DIRECTORY}/pt-summary" > "${OUT_DIR}/pt-summary"

    # Some stuff that only can be collected when ran as OS-root
    if [[ ${RUNASROOT} -eq 1 ]]; then

        sysctl -a > "${OUT_DIR}/sysctl" || true
        dmesg > "${OUT_DIR}/dmesg"

        # Listening tcp ports
        if check_binary ss; then
            ss -nltp > "${OUT_DIR}/tcp_listen_ports"
        fi

        # LVM
        if check_binary lvdisplay; then
            lvdisplay > "${OUT_DIR}/lvdisplay"
            lvdisplay -vm > "${OUT_DIR}/lvdisplay_vm"
        fi
        if check_binary vgdisplay; then
            vgdisplay > "${OUT_DIR}/vgdisplay"
        fi
        if check_binary pvdisplay; then
            pvdisplay > "${OUT_DIR}/pvdisplay"
        fi
        if check_binary lvs; then
            lvs --segments > "${OUT_DIR}/lvdisplay_segments"
        fi

        # Other
        if check_binary dmidecode; then
            dmidecode > "${OUT_DIR}/dmidecode"
        fi

        # collecting cron jobs from crontab, and from /etc/cron.d/
        find /var/spool/cron/ -type f -print -exec cat {} \; > "${OUT_DIR}/crontab_spool_users"
        find /etc/cron.d/ -type f -print -exec cat {} \; > "${OUT_DIR}/crontab_crond"
        cat /etc/crontab > "${OUT_DIR}/crontab_etc"

    fi

    # If LVM is being used, but not run as root, we can get the dm-* numbers
    # by looking at /dev/mapper device numbers.
    # This is useful when looking at the PCS graphs and trying to match DM disks
    # with mounted filesystems.
    test -d /dev/mapper && ls -alhs /dev/mapper/ > "${OUT_DIR}/dev_mapper"

    if check_binary lspci; then
        lspci > "${OUT_DIR}/lspci"
    fi
    if check_binary ip; then
        ip addr > "${OUT_DIR}/ip"
    fi
    if check_binary ifconfig; then
        ifconfig > "${OUT_DIR}/ifconfig"
    fi
    if check_binary netstat; then
        netstat -s > "${OUT_DIR}/netstat"
    fi
    if check_binary route; then
        route -n > "${OUT_DIR}/route"
    fi
    # get full options of mounted fs
    cat /proc/mounts > "${OUT_DIR}/mounts"

    # get info related to NUMA
    if check_binary numactl; then
        numactl --hardware > "${OUT_DIR}/numa"
        numactl --show >> "${OUT_DIR}/numa"
    fi
    if check_binary numastat; then
        numastat -m > "${OUT_DIR}/numa_stat"
    fi

    # lscpu can also provide us numa info
    if check_binary lscpu; then
        lscpu > "${OUT_DIR}/lscpu"
    fi

    # get info related to memory and disk
    free -m > "${OUT_DIR}/free"
    df -h > "${OUT_DIR}/df"

    # get oom_score_adj
    if [[ -f "/proc/${PIDTOUSE}/oom_score_adj" ]]; then
        cat "/proc/${PIDTOUSE}/oom_score_adj" > "${OUT_DIR}/oom_score_adj"
    fi

    function get_disk_of_file_info {
        local filename="$1"
        local outfile="$2"
        local datadisk

        echo "${filename}" > "${OUT_DIR}/${outfile}"

        # fast fail if cannot get file info
        if ! df "${filename}" &> /dev/null; then
            echo "!! Cannot read '${filename}', thus no disk info for file path. Need to run as root?"
            return 1
        fi

        # have permissions to read
        grep " $(df -P "${filename}" | awk 'NR==1 {next} {print $6; exit}') " /proc/mounts | tail -n 1 >> "${OUT_DIR}/${outfile}"
        datadisk=$(readlink -f "$(grep " $(df -P "${filename}" | awk 'NR==1 {next} {print $6; exit}') " /proc/mounts | tail -n 1 | cut -d' ' -f1)")

        # shellcheck disable=SC2129  # Ignore multi-exec redirect
        echo "${datadisk}" >> "${OUT_DIR}/${outfile}"
        df -P -h "$(df -P "${filename}" | awk 'NR==1 {next} {print $6; exit}')" | tail -n 1 >> "${OUT_DIR}/${outfile}"

        # Need to be root to exec du on most directories
        if [[ ${RUNASROOT} -eq 1 ]]; then
            du -sh "${filename}" >> "${OUT_DIR}/${outfile}"
        fi

        if echo "${datadisk} " | grep 'dm-' > /dev/null 2>&1; then
            pvs | grep "$(lvdisplay | awk '/LV Name/{n=$3} /VG Name/{v=$3} /Block device/{d=$3; sub(".*:","dm-",d); print d,n,v;}' | grep "${datadisk/\/dev\//}" | awk '{print $3}')" | awk '{print $1}' >> "${OUT_DIR}/datadir"
        fi
    }

    ## Db Sysconfig Post
    get_disk_of_file_info "${variables_datadir}" datadir_disk_info
    get_disk_of_file_info "${variables_tmpdir}" tmpdir_disk_info

    echo "Done."
else
    echo "Environment is RDS. Not collecting system info."
fi

## Database Information

echo -n "Executing pt-mysql-summary..."
"${PT_DIRECTORY}"/pt-mysql-summary -- "${DB_CLI_OPTIONS[@]}" > "${OUT_DIR}"/pt-mysql-summary 2> /dev/null
echo "Done"

##
echo -n "Collecting MySQL config info... "

# innodb_stats_on_metadata old value
echo "${variables_innodb_stats_on_metadata}" > "${OUT_DIR}/default_metadata_value"

"${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -NBe "SHOW GLOBAL VARIABLES" > "${OUT_DIR}/mysql_variables" 2> /dev/null
"${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -NBe "SHOW GLOBAL STATUS" > "${OUT_DIR}/mysql_global_status" 2> /dev/null
"${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -NBe "SHOW ENGINE INNODB STATUS\G" > "${OUT_DIR}/mysql_innodb_status" 2> /dev/null

# RDS Doesn't Grant SUPER nor REPLICATION CLIENT privs
if [[ ${ISRDS} -eq 0 ]]; then
    "${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -Be "SHOW SLAVE STATUS\G" > "${OUT_DIR}/mysql_slave_status" 2> /dev/null
    "${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -Be "SHOW MASTER STATUS\G" > "${OUT_DIR}/mysql_master_status" 2> /dev/null
fi

if [[ ${ISRDS} -eq 0 ]]; then
    touch "${OUT_DIR}/cmdline"
    pgrep "docker-prox" | awk '{print $1}' |
        while read -r pid; do
            cat "/proc/${pid}/cmdline" && echo
        done >> "${OUT_DIR}/cmdline"
fi

# check_tmp_dir and my.cnf if not RDS
if [[ ${ISRDS} -eq 0 ]]; then
    if check_binary "lsof"; then
        lsof -p "${PIDTOUSE}" | grep del > "${OUT_DIR}/tmpdir_lsof"
    fi
    MY_CNF=""
    test -f "/etc/my.cnf" && MY_CNF="/etc/my.cnf"
    test -f "/etc/mysql/my.cnf" && MY_CNF="/etc/mysql/my.cnf"
    if ! test -z "${MY_CNF}"; then
        "${PT_DIRECTORY}/pt-config-diff" "${DB_CLI_OPTIONS[@]}" localhost "${MY_CNF}" > "${OUT_DIR}/pt-config-diff"
        cp "${MY_CNF}" "${OUT_DIR}/my.dot.cnf"

        # Look for any singular included config files
        grep "^\!include " "${MY_CNF}" | awk '{print $2}' | while read -r line; do
            f="${line}"
            if [[ ${line} == "$(basename "${line}")" ]]; then
                f="$(dirname "${MY_CNF}")/${line}"
            fi
            cp "${f}" "${OUT_DIR}/my.dot.cnf_$(basename "${f}")"
        done

        # Look for any config files in included directories
        grep "^\!includedir " "${MY_CNF}" | awk '{print $2}' | while read -r line; do
            if test -d "${line}"; then
                find "${line}" -type f -name "*.cnf" -exec sh -c 'cp "$1" ""$2"/my.dot.cnf_$(basename "$1")"' sh {} "${OUT_DIR}" ';'
            fi
        done
    else
        echo "!!! Did not find /etc/my.cnf or /etc/mysql/my.cnf !!!" | tee "${OUT_DIR}/pt-config-diff"
    fi
fi

echo "Done."

#############################
if [[ ${ISRDS} -eq 0 ]]; then
    echo -n "Collecting Error Log... "
    if [[ -r ${variables_log_error} ]]; then
        tail -n 1000 "${variables_log_error}" > "${OUT_DIR}/error_log"
        echo "Done."
    else
        echo "Unable to read ${variables_log_error}" | tee "${OUT_DIR}/error_log"
    fi
fi

## get mysql version
MAJOR_VERSION=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" --skip-column-names -e "SELECT SUBSTRING_INDEX(SUBSTRING_INDEX(VERSION(), '-', 1), '.', 1);" 2> /dev/null)
MINOR_VERSION=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" --skip-column-names -e "SELECT SUBSTRING_INDEX(SUBSTRING_INDEX(SUBSTRING_INDEX(VERSION(), '-', 1), '.', 2), '.', -1);" 2> /dev/null)
RELEASE_VERSION=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" --skip-column-names -e "SELECT SUBSTRING_INDEX(SUBSTRING_INDEX(SUBSTRING_INDEX(VERSION(), '-', 1), '.', 3), '.', -1);" 2> /dev/null)

#############################
if [[ ${TOO_MANY_TABLES} -eq 0 ]]; then
    echo -n "Collecting MySQL Schema... "

    colstats=""
    if [[ ${MAJOR_VERSION} -ge 8 ]]; then
        colstats="--column-statistics=1"
    fi

    "${MYSQLBASEDIR}/mysqldump" "${DB_CLI_OPTIONS[@]}" "${colstats}" -f --set-gtid-purged=OFF --no-data --triggers --routines --set-charset --all-databases --lock-tables=false > "${OUT_DIR}/mysql_schema" 2> /dev/null

    echo "Done."
else
    echo "There are many tables on the server, so we skipped the schema collection that might can cause problems."
fi

#############################
if [[ ${TOO_MANY_TABLES} -eq 0 ]]; then
    echo -n "Running pt-duplicate-key-checker, this may take a while... "
    "${PT_DIRECTORY}/pt-duplicate-key-checker" "${DB_CLI_OPTIONS[@]}" > "${OUT_DIR}/pt-duplicate-key-checker"
    echo "Done."
else
    echo "There are many tables on the server, so we skipped pt-duplicate-key-checker."
fi

# get MySQL flavor
DBMS_NAME=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" --skip-column-names -e "SELECT IF(@@global.version_comment LIKE '%mariadb%', 'MariaDB', IF(@@global.version_comment LIKE '%percona%', 'Percona Server', 'MySQL'));" 2> /dev/null)

#############################
if [[ ${ISRDS} -eq 1 ]]; then
    echo "Environment is RDS. Not collecting MySQL datadir sizes"
elif [[ -d ${variables_datadir} ]]; then
    if [[ ${RUNASROOT} -eq 1 ]]; then
        echo -n "Collecting MySQL disk usage info (datadir = ${variables_datadir})... "
        du -sh "${variables_datadir}" >> "${OUT_DIR}/data_usage_raw"
        find "${variables_datadir}" \( -name "*.ibd" -or -name "ibdata*" \) -print0 | xargs -0 du -shc | tail -1 > "${OUT_DIR}/data_usage_innodb_raw"
        # MyISAM
        find "${variables_datadir}" -name "*.MYD" -print0 | xargs -0 du -shc | tail -1 > "${OUT_DIR}/data_usage_myisam_data_raw"
        find "${variables_datadir}" -name "*.MYI" -print0 | xargs -0 du -shc | tail -1 >> "${OUT_DIR}/data_usage_myisam_index_raw"
        # Aria
        if [[ ${DBMS_NAME} == "MariaDB" ]]; then
            find "${variables_datadir}" -name "*.MAD" -print0 | xargs -0 du -shc | tail -1 > "${OUT_DIR}/data_usage_aria_data_raw"
            find "${variables_datadir}" -name "*.MAI" -print0 | xargs -0 du -shc | tail -1 >> "${OUT_DIR}/data_usage_aria_index_raw"
        fi
        echo "Done."
    else
        echo "Cannot collect MySQL disk usage info as non-root user"
    fi
else
    echo "Can't find the MySQL datadir; Will skip collection data info."
fi

#############################
echo "Collecting MySQL table and engine info... "

## set query items that depend on MySQL version/flavor
if [[ ${DBMS_NAME} == "MariaDB" ]]; then
    PASSWORD_COLUMN="password"
elif [[ ${MAJOR_VERSION} -ge 8 ]]; then
    PASSWORD_COLUMN="authentication_string"
elif [[ ${MAJOR_VERSION} -eq 5 ]] && [[ ${MINOR_VERSION} -eq 7 ]] && [[ ${RELEASE_VERSION} -ge 6 ]]; then
    PASSWORD_COLUMN="authentication_string"
else
    PASSWORD_COLUMN="password"
fi

## plugins
sql_to_file 'SHOW PLUGINS' 'SHOW PLUGINS' 'plugins'

## engines
sql_to_file 'SHOW ENGINES' 'SHOW ENGINES' 'engines'

if [[ ${TOO_MANY_TABLES} -eq 0 ]]; then

    ## overall dataset size
    sql="
  SELECT CONCAT(ROUND(SUM(data_length) / (1024*1024*1024),2),'G') Data_Size,
    CONCAT(ROUND(SUM(index_length)/ (1024*1024*1024),2),'G') Index_Size,
    CONCAT(ROUND((sum(data_length)+sum(index_length))/(1024*1024*1024), 2),'G') Total_Size
  FROM information_schema.TABLES
  WHERE TABLE_SCHEMA NOT IN ('information_schema', 'performance_schema', 'sys')
  GROUP BY NULL
  "
    sql_to_file 'Overall Dataset Size' "${sql}" 'dataset'

    ## storage engine usage
    sql="
  SELECT ENGINE AS Storage_Engine, COUNT(*) Tables_Count,
    CONCAT(ROUND(SUM(data_length) / (1024*1024*1024),2),'G') Data_Size,
    CONCAT(ROUND(SUM(index_length)/ (1024*1024*1024),2),'G') Index_Size,
    CONCAT(ROUND((sum(data_length)+sum(index_length))/(1024*1024*1024), 2),'G') Total_Size
  FROM information_schema.TABLES
  WHERE ENGINE IS NOT NULL
    AND table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
  GROUP BY ENGINE WITH ROLLUP;
  "
    sql_to_file 'Storage Engine Usage' "${sql}" 'engine_usage'

    ## top 10 largest tables
    sql="
  SELECT CONCAT(table_schema, '.', table_name) as Schema_Table, ENGINE AS Storage_Engine,
    CONCAT(ROUND(table_rows/1000000,2),'M') Rows_Count,
    CONCAT(ROUND(data_length/(1024*1024*1024),2),'G') Data_Size,
    CONCAT(ROUND(index_length/(1024*1024*1024 ),2),'G') Index_Size,
    CONCAT(ROUND(( data_length+index_length)/(1024*1024*1024),2),'G') Total_Size,
    ROUND(index_length / data_length, 2) Index_Fraction
  FROM information_schema.TABLES
  WHERE table_schema NOT IN ('information_schema', 'performance_schema', 'sys')
  ORDER BY data_length + index_length DESC LIMIT 10;
  "
    sql_to_file 'Top 10 Tables' "${sql}" 'top10_large_tables'

    ## MyISAM table sizes
    sql="
  SELECT table_schema, table_name, table_rows,
    CONCAT(ROUND((index_length+data_length)/1024/1024),'MB') AS total_size
  FROM information_schema.TABLES
  WHERE engine='myisam' AND table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys');
  "
    sql_to_file 'MyISAM Data/Index Usage' "${sql}" 'mysql_myisam_tables'

    ## Aria table sizes
    if [[ ${DBMS_NAME} == "MariaDB" ]]; then
        sql="
    SELECT table_schema, table_name, table_rows as rows_count,
      CONCAT(ROUND((index_length+data_length)/1024/1024),'MB') AS total_size
    FROM information_schema.TABLES
    WHERE engine='aria' AND table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys');
    "
        sql_to_file 'Aria Data/Index Usage' "${sql}" 'mysql_aria_tables'
    fi

    ## fulltext index info
    sql="
   SELECT S.table_schema, S.table_name, S.column_name, T.ENGINE AS storage_engine
   FROM information_schema.STATISTICS S
   JOIN information_schema.TABLES T ON S.TABLE_SCHEMA=T.TABLE_SCHEMA
     AND S.TABLE_NAME = T.TABLE_NAME
   WHERE S.index_type = 'FULLTEXT'
     AND T.table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys');
  "
    sql_to_file 'FULLTEXT index statistics' "${sql}" 'mysql_full_text'

    ## per-engine data usage
    sql="
  SELECT COUNT(*) AS Tables_Count,
    CONCAT(ROUND(SUM(data_length) / ( 1024 * 1024 * 1024 ), 2), 'G') Data_Size,
    CONCAT(ROUND(SUM(index_length) / ( 1024 * 1024 * 1024 ), 2), 'G') Index_Size,
    CONCAT(SUM(ROUND(( data_length + index_length ) /
    ( 1024 * 1024 * 1024 ), 2)), 'G') Total_Size, engine AS Storage_Engine
  FROM information_schema.TABLES
  WHERE TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND TABLE_TYPE <> 'VIEW'
  GROUP BY engine;
  "
    sql_to_file 'Data/Index Usage By Engine' "${sql}" 'data_usage_by_storage_engine'

    ## top 100 table usage
    sql="
  SELECT CONCAT(table_schema, '.', table_name) Schema_Table,
    CONCAT(ROUND(table_rows / 1000000, 2), 'M') Rows_Count,
    CONCAT(ROUND(data_length / ( 1024 * 1024 * 1024 ), 2), 'G') Data_Size,
    CONCAT(ROUND(index_length / ( 1024 * 1024 * 1024 ), 2), 'G') Index_Size,
    CONCAT(ROUND(( data_length + index_length ) / ( 1024 * 1024 * 1024 ), 2), 'G') Total_Size,
    ROUND(index_length / data_length, 2) Index_Fraction
  FROM  information_schema.TABLES
  WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND TABLE_TYPE <> 'VIEW'
  ORDER BY data_length + index_length DESC LIMIT 100
  "
    sql_to_file 'Data/Index Usage By Table, Top 100' "${sql}" 'data_usage_by_table'

    ## per-schema usage
    sql="
  SELECT table_schema,
    ROUND(SUM(data_length+index_length)/1024/1024/1024, 2) as Total_Size_GB,
    ROUND(SUM(data_length)/1024/1024/1024,2) as Data_Size_GB,
    ROUND(SUM(index_length)/1024/1024/1024,2) as Index_Size_GB
  FROM information_schema.tables
  WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND TABLE_TYPE <> 'VIEW'
  GROUP BY 1 ORDER BY 2 DESC
  "
    sql_to_file 'Data/Index Usage By Schema' "${sql}" 'data_usage_by_schema'

    ## MyISAM data usage
    sql="
  SELECT CONCAT(table_schema, '.', table_name) Schema_Table,
    CONCAT(ROUND(table_rows / 1000000, 2), 'M') Rows_Count,
    CONCAT(ROUND(data_length / ( 1024 * 1024 * 1024 ), 2), 'G') Data_Size,
    CONCAT(ROUND(index_length / ( 1024 * 1024 * 1024 ), 2), 'G') Index_Size,
    CONCAT(ROUND(( data_length + index_length ) / ( 1024 * 1024 * 1024 ), 2), 'G') Total_Size,
    ROUND(index_length / data_length, 2) Index_Fraction
  FROM information_schema.TABLES
  WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND TABLE_TYPE <> 'VIEW' AND engine='MyISAM'
  ORDER BY data_length + index_length DESC LIMIT 100
  "
    sql_to_file 'Data/Index Usage of MyISAM' "${sql}" 'data_usage_by_myisam_tables'

    if [[ ${DBMS_NAME} == "MariaDB" ]]; then
        ## Aria data usage
        sql="
    SELECT CONCAT(table_schema, '.', table_name) Schema_Table,
      CONCAT(ROUND(table_rows / 1000000, 2), 'M') Rows_Count,
      CONCAT(ROUND(data_length / ( 1024 * 1024 * 1024 ), 2), 'G') Data_Size,
      CONCAT(ROUND(index_length / ( 1024 * 1024 * 1024 ), 2), 'G') Index_Size,
      CONCAT(ROUND(( data_length + index_length ) / ( 1024 * 1024 * 1024 ), 2), 'G') Total_Size,
      ROUND(index_length / data_length, 2) Index_Fraction
    FROM information_schema.TABLES
    WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
      AND TABLE_TYPE <> 'VIEW' AND engine='Aria'
    ORDER BY data_length + index_length DESC LIMIT 100
    "
        sql_to_file 'Data/Index Usage of Aria' "${sql}" 'data_usage_by_aria_tables'
    fi

    ## partition info
    sql="
  SELECT COUNT(*) AS PARTS_COUNT, TABLE_SCHEMA, TABLE_NAME, PARTITION_EXPRESSION
  FROM information_schema.PARTITIONS
  WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
  GROUP BY TABLE_SCHEMA, TABLE_NAME, PARTITION_EXPRESSION HAVING COUNT(*) > 1;
  "
    sql_to_file 'Tables with Partitions' "${sql}" 'tables_with_partitions'

    ## More partitions
    sql="
  SELECT TABLE_SCHEMA, TABLE_NAME, PARTITION_METHOD, PARTITION_EXPRESSION, SUM(TABLE_ROWS) TABLE_ROWS
  FROM information_schema.partitions
  WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND PARTITION_METHOD IS NOT NULL
  GROUP BY TABLE_SCHEMA, TABLE_NAME, PARTITION_METHOD, PARTITION_EXPRESSION;
  "
    sql_to_file 'Partition Statistics' "${sql}" 'tables_with_partitioning'

    ## InnoDB compression info
    sql_to_file 'InnoDB Compressed Tables' "SELECT * FROM INFORMATION_SCHEMA.INNODB_CMP;" 'tables_innodb_compression'

    ## InnoDB compression bp
    sql_to_file 'InnoDB Compressed Tables in Bufferpool' "SELECT * FROM INFORMATION_SCHEMA.INNODB_CMPMEM;" 'tables_with_compression_bp'

    ## InnoDB row formats
    sql="
  SELECT TABLE_SCHEMA, TABLE_NAME, ROW_FORMAT
  FROM INFORMATION_SCHEMA.TABLES
  WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND ENGINE='InnoDB';
  "
    sql_to_file 'InnoDB Row Formats' "${sql}" 'tables_innodb_format'

    ## Tables missing PK
    sql="
  SELECT tables.table_schema, tables.table_name, tables.table_rows
  FROM information_schema.tables
  LEFT JOIN (
    SELECT table_schema, table_name
    FROM information_schema.statistics
    GROUP BY table_schema, table_name, index_name
    HAVING
      SUM(
        CASE WHEN non_unique = 0 AND nullable != 'YES' THEN 1 ELSE 0 END
      ) = COUNT(*)
  ) puks
  ON tables.table_schema = puks.table_schema AND tables.table_name = puks.table_name
  WHERE puks.table_name IS NULL
    AND tables.table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND tables.table_type = 'BASE TABLE' AND engine='InnoDB';
  "
    sql_to_file 'Tables Missing PK' "${sql}" 'tables_without_primarykey'

    ## Multiple auto increments
    sql="
  SELECT CONCAT(a.table_schema,'.', a.TABLE_NAME) AS Table_Schema, SUM(a.table_rows) AS Rows_Count,
    CONCAT(ROUND((sum(a.index_length)+sum(a.data_length))/1024/1024),'MB') AS Table_Size,
    COUNT(b.COLUMN_NAME) AS Columns_In_Auto_Inc
  FROM information_schema.TABLES AS a
  JOIN information_schema.COLUMNS AS b ON b.TABLE_NAME = a.TABLE_NAME
    AND b.TABLE_SCHEMA = a.TABLE_SCHEMA
  WHERE engine = 'myisam'
    AND a.table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND b.EXTRA='auto_increment'
  GROUP BY (1);
  "
    sql_to_file 'Tables with Multiple A_I' "${sql}" 'mysql_tables_with_multiple_autoinc'

    ## Non-optimal PK
    sql="
  SELECT a.TABLE_SCHEMA AS 'SCHEMA', a.TABLE_NAME,
    GROUP_CONCAT(a.COLUMN_NAME) AS 'COLUMN',
    GROUP_CONCAT(a.column_type) AS 'TYPE', SUM(b.TABLE_ROWS) AS table_rows
  FROM information_schema.COLUMNS AS a
  JOIN information_schema.TABLES AS b ON b.TABLE_NAME = a.TABLE_NAME
    AND b.TABLE_SCHEMA = a.TABLE_SCHEMA
  WHERE b.table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND COLUMN_KEY='PRI'
    AND ENGINE IN ('InnoDB', 'TokuDB')
    AND
    ( UPPER(DATA_TYPE) LIKE '%TEXT%'
      OR UPPER(DATA_TYPE) LIKE '%BLOB%'
      OR UPPER(DATA_TYPE) LIKE '%CHAR%'
      OR UPPER(DATA_TYPE) LIKE '%BINARY%' )
    AND TABLE_ROWS > 1000
  GROUP BY 1, 2;
  "
    sql_to_file 'Tables with non-optimal PK' "${sql}" 'mysql_tables_without_optimalPK'

    ## Tables in 5.5 time format
    if [[ ${MAJOR_VERSION} -eq 5 ]] && [[ ${MINOR_VERSION} -eq 6 ]]; then

        echo " - Tables with 5.5 DATETIME format"

        sql="
    SELECT t.table_schema, t.engine, t.table_name, c.column_name, c.column_type
    FROM information_schema.tables AS t
    INNER JOIN information_schema.columns AS c ON c.table_schema = t.table_schema
      AND c.table_name = t.table_name
    LEFT OUTER JOIN information_schema.innodb_sys_tables AS ist
      ON ist.name = concat(t.table_schema,'/',t.table_name)
    LEFT OUTER JOIN information_schema.innodb_sys_columns AS isc
      ON isc.table_id = ist.table_id AND isc.name = c.column_name
    WHERE c.column_type IN ('time','timestamp','datetime')
      AND t.table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
      AND t.table_type = 'base table'
      AND (t.engine = 'innodb' and isc.mtype = 6)
    ORDER BY t.table_schema, t.table_name, c.column_name;
    "
        sql_to_file 'Tables in 5.5 time format' "${sql}" 'mysql_tables_in_55_time_format'

        ## Sum tables with 5.5 and 5.6 DATETIME format
        sql="
    SELECT case isc.mtype when '6' then '5.5' when '3' then '5.6' end FORMAT, count(*) TOTAL
    FROM information_schema.tables AS t
    INNER JOIN information_schema.columns AS c
      ON c.table_schema = t.table_schema  AND c.table_name = t.table_name
    LEFT OUTER JOIN information_schema.innodb_sys_tables AS ist
      ON ist.name = concat(t.table_schema,'/',t.table_name)
    LEFT OUTER JOIN information_schema.innodb_sys_columns AS isc
      ON isc.table_id = ist.table_id AND isc.name = c.column_name
    WHERE c.column_type IN ('time','timestamp','datetime')
      AND t.table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
      AND t.table_type = 'base table' AND (t.engine = 'innodb' )
    GROUP BY isc.mtype;
    "
        sql_to_file 'Sum tables with 5.5 and 5.6 DATETIME format' "${sql}" 'mysql_tables_in_55_time_format_sum'

    fi

    ## AUTO_INCREMENT_FILL
    sql="
  SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE,
    IF(LOCATE('unsigned', COLUMN_TYPE) > 0,1,0) AS IS_UNSIGNED,
    (
      CASE DATA_TYPE
        WHEN 'tinyint' THEN 255
        WHEN 'smallint' THEN 65535
        WHEN 'mediumint' THEN 16777215
        WHEN 'int' THEN 4294967295
        WHEN 'bigint' THEN 18446744073709551615
      END >> IF(LOCATE('unsigned', COLUMN_TYPE) > 0, 0, 1)
    ) AS MAX_VALUE,
    AUTO_INCREMENT, ROUND(
    AUTO_INCREMENT / (
      CASE DATA_TYPE
        WHEN 'tinyint' THEN 255
        WHEN 'smallint' THEN 65535
        WHEN 'mediumint' THEN 16777215
        WHEN 'int' THEN 4294967295
        WHEN 'bigint' THEN 18446744073709551615
      END >> IF(LOCATE('unsigned', COLUMN_TYPE) > 0, 0, 1)
    )*100) AS AUTO_INCREMENT_RATIO
  FROM INFORMATION_SCHEMA.COLUMNS
    INNER JOIN INFORMATION_SCHEMA.TABLES USING (TABLE_SCHEMA, TABLE_NAME)
  WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND EXTRA='auto_increment' HAVING AUTO_INCREMENT_RATIO>60 ORDER BY CAST(AUTO_INCREMENT_RATIO AS SIGNED INTEGER) DESC LIMIT 10;  ;
  "
    sql_to_file 'Auto increment fill' "${sql}" 'mysql_autoincrement_fill'

    ## Geometry missing SRID
    if [[ ${MAJOR_VERSION} -ge 8 ]]; then
        sql="
    SELECT TABLE_SCHEMA AS 'SCHEMA', TABLE_NAME, COLUMN_NAME, UPPER(DATA_TYPE) AS 'TYPE', SRS_ID
    FROM information_schema.COLUMNS
    WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
      AND
      ( UPPER(DATA_TYPE) LIKE 'GEOMETRY%'
        OR UPPER(DATA_TYPE) LIKE '%POINT'
        OR UPPER(DATA_TYPE) LIKE '%LINESTRING'
        OR UPPER(DATA_TYPE) LIKE '%POLYGON' )
      AND SRS_ID IS NULL;
    "
        sql_to_file 'Tables with missing SRID' "${sql}" 'mysql_tables_without_optimalGEO'
    fi

    ## ROW FORMAT of InnoDB Tables with TEXT/BLOB
    sql="
  SET SESSION sql_mode = REPLACE(@@session.sql_mode, 'ONLY_FULL_GROUP_BY', '');
  SELECT CONCAT(t1.table_schema, '.', t1.table_name) as Schema_Table, ROW_FORMAT, count(*) as Total_TEXT_BLOB_Cols
  FROM INFORMATION_SCHEMA.COLUMNS t1
  JOIN INFORMATION_SCHEMA.TABLES t2
  ON t2.TABLE_SCHEMA=t1.TABLE_SCHEMA AND t2.TABLE_NAME=t1.TABLE_NAME
  WHERE t1.table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND DATA_TYPE IN ('text','blob') AND ENGINE='InnoDB'
  GROUP BY 1 ORDER BY 2 desc;
  "
    sql_to_file 'Row Format of InnoDB Tables with TEXT/BLOB columns' "${sql}" 'mysql_innodb_row_format_blob'

    ## Non-Local Root Accounts
    sql="
  SELECT user, host
  FROM mysql.user
  WHERE user = 'root' AND host != 'localhost' AND host != '127.0.0.1';
  "
    sql_to_file 'Non-Local Root Accounts' "${sql}" 'non_local_root_accounts'

    ## Anonymous Accounts
    sql="
  SELECT user, host
  FROM mysql.user
  WHERE user = '';
  "
    sql_to_file 'Anonymous User Accounts' "${sql}" 'anonymous_accounts'

    ## Accounts From Any Host
    sql="
  SELECT user
  FROM mysql.user
  WHERE host = '%' OR host = '' /*M!100005 AND is_role = 'N' */;
  "
    sql_to_file 'Accounts Accessible From Any Host' "${sql}" 'accounts_from_any_host'

    ## Accounts with Identical Non-Empty passwords
    sql="
  SELECT GROUP_CONCAT(DISTINCT user) Users_With_Identical_Passwds, count(*) as Times_Passwd_Is_Used
  FROM mysql.user
  WHERE ${PASSWORD_COLUMN} != '' /*M!100005 AND is_role = 'N' */
  GROUP BY ${PASSWORD_COLUMN} HAVING COUNT(${PASSWORD_COLUMN}) > 1;
  "
    sql_to_file 'Accounts with Identical Non-Empty passwords' "${sql}" 'accounts_with_identical_passwords'

    ## Non-Root All Privs
    numPrivs=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -BNe "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = 'mysql' and table_name = 'user' and column_name LIKE '%_priv'" 2> /dev/null)
    privsString=$("${MYSQLBASEDIR}/mysql" "${DB_CLI_OPTIONS[@]}" -BNe "SELECT GROUP_CONCAT(column_name SEPARATOR ',') AS cols FROM information_schema.columns WHERE table_schema = 'mysql' AND table_name = 'user' AND column_name LIKE '%_priv'" 2> /dev/null)
    sql="
  SELECT user
  FROM mysql.user
  WHERE user != 'root' AND CONCAT_WS('', ${privsString}) REGEXP 'Y\{${numPrivs}\}';
  "
    sql_to_file 'Non-Root Accounts with All Privileges' "${sql}" 'non_root_all_privs'

    ## Non-Root with Admin Privs
    sql="
  SELECT user, host
  FROM mysql.user
  WHERE (Shutdown_Priv = 'Y' OR Super_Priv = 'Y' OR Reload_Priv = 'Y') AND user != 'root'
  "
    sql_to_file 'Non-Root Accounts with Admin Privileges' "${sql}" 'non_root_admin_privs'

    ## Account with empty password
    sql="
  SELECT CONCAT(user, '@', host) AS User_Account
  FROM mysql.user
  WHERE ${PASSWORD_COLUMN} = '' /*M!100005 AND is_role = 'N' */;
  "
    sql_to_file 'Account with empty password' "${sql}" 'account_empty_passwd'

    ## Account SSL connection enforcement
    sql="
  SELECT CONCAT(user, '@', host) AS User_Account,
  CASE
    WHEN ssl_type IN ('ANY', 'X509', 'SPECIFIED') THEN 'SSL_Required'
    ELSE 'SSL_Not_Required'
  END AS SSL_Required
  FROM mysql.user
  ORDER BY SSL_Required DESC;
  "
    sql_to_file 'Account SSL connection enforcement' "${sql}" 'account_require_ssl_status'

    ##FILE_FORMAT and ROW_FORMAT
    if [[ ${MAJOR_VERSION} -eq 8 ]] && [[ ${MINOR_VERSION} -ge 0 ]] && [[ ${RELEASE_VERSION} -ge 3 ]]; then
        sql="
    SELECT ROW_FORMAT, COUNT(*) Total_by_Format
    FROM INFORMATION_SCHEMA.INNODB_TABLES
    GROUP BY ROW_FORMAT;
    "
    else
        # Pre-8.0.3
        sql="
    SELECT FILE_FORMAT, ROW_FORMAT, COUNT(*) Total_by_Format
    FROM INFORMATION_SCHEMA.INNODB_SYS_TABLES
    GROUP BY FILE_FORMAT, ROW_FORMAT;
    "
    fi
    sql_to_file 'File and Row format of InnoDB Tables' "${sql}" 'mysql_innodb_file_format'

    ##FRAGMENTED/FREE SPACE in InnoDB TABLES
    sql="
  SELECT table_schema, table_name, CONCAT(ROUND((data_free / 1024 / 1024),2),'MB') data_free
  FROM information_schema.tables
  WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND ENGINE LIKE 'InnoDB' AND data_free > 100 * 1024 *  1024;
  "
    sql_to_file 'Fragmented/free space in InnoDB Tables (>100MB)' "${sql}" 'mysql_innodb_free_space'

    ##TABLES IN ibdata1
    innodbsystable="INNODB_SYS_TABLES"
    if [[ ${MAJOR_VERSION} -eq 8 ]] && [[ ${MINOR_VERSION} -ge 0 ]] && [[ ${RELEASE_VERSION} -ge 3 ]]; then
        innodbsystable="INNODB_TABLES"
    fi
    sql="
  SELECT NAME
  FROM INFORMATION_SCHEMA.${innodbsystable}
  WHERE SPACE=0 AND NAME NOT LIKE 'SYS_%';
  "
    sql_to_file 'Tables in ibdata1 (table space 0)' "${sql}" 'mysql_innodb_ibdata'

    ##TABLE WITH BLOB/TEXT SIZE and PK and nb MUL
    sql="
  SET SESSION sql_mode = REPLACE(@@session.sql_mode, 'ONLY_FULL_GROUP_BY', '');
  SELECT CONCAT (TABLES.table_schema,'.', TABLES.table_name) as Table_Name,
    CONCAT(ROUND(( data_length + index_length ) / ( 1024 * 1024 * 1024 ), 2), 'G') Total_Size,
    CONCAT(ROUND(data_length / ( 1024 * 1024 * 1024 ), 2), 'G') Data_Size,
    CONCAT(ROUND(index_length / ( 1024 * 1024 * 1024 ), 2), 'G') Index_Size, table_rows AS Total_Rows,
    CONCAT(ROUND((data_free / 1024 / 1024),2),'M')  AS Data_Free,
    GROUP_CONCAT(if(STRCMP(COLUMN_KEY,'PRI'),NULL,COLUMN_TYPE)) as  PK_Type ,
    SUM(if(STRCMP(COLUMN_KEY,'MUL'),0,1)) AS Secndry_Keys,
    SUM(if(FIND_IN_SET(COLUMN_TYPE,'blob,longblog,mediumblob,text,longtext,mediumtext')>0,1,0)) AS BLOB_Cols
  FROM information_schema.TABLES
  JOIN information_schema.COLUMNS
    ON COLUMNS.TABLE_NAME = TABLES.TABLE_NAME AND COLUMNS.TABLE_SCHEMA = TABLES.TABLE_SCHEMA
  WHERE TABLES.table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND ENGINE LIKE 'InnoDB' GROUP BY 1,2 ORDER  BY 9 desc;
  "
    sql_to_file 'Tables Size with BloB, Text and PK and MUL' "${sql}" 'mysql_innodb_blobtext'

    ## Select Foreign Keys
    sql="
  SELECT CONSTRAINT_SCHEMA, CONSTRAINT_NAME, TABLE_SCHEMA, TABLE_NAME
  FROM information_schema.TABLE_CONSTRAINTS
  WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
    AND CONSTRAINT_TYPE= 'FOREIGN KEY';
  "
    sql_to_file 'Select Foreign Keys' "${sql}" 'mysql_foreign_keys'

    ## List all Triggers
    sql="
  SELECT TRIGGER_NAME, EVENT_MANIPULATION, EVENT_OBJECT_SCHEMA, EVENT_OBJECT_TABLE
  FROM information_schema.TRIGGERS
  ORDER BY EVENT_OBJECT_SCHEMA;
  "
    sql_to_file 'List Triggers' "${sql}" 'mysql_triggers'

    ## List all Procedures
    sql="
  SELECT ROUTINE_SCHEMA, ROUTINE_NAME, ROUTINE_TYPE
  FROM information_schema.ROUTINES
  WHERE ROUTINE_TYPE = 'PROCEDURE'
  order by ROUTINE_SCHEMA;
  "
    sql_to_file 'List Procedures' "${sql}" 'mysql_procedures'

    ## List all Functions
    sql="
  SELECT ROUTINE_SCHEMA, ROUTINE_NAME, ROUTINE_TYPE, DATA_TYPE
  FROM information_schema.ROUTINES
  WHERE ROUTINE_TYPE = 'FUNCTION'
  ORDER BY ROUTINE_SCHEMA;
  "
    sql_to_file 'List Functions' "${sql}" 'mysql_functions'

    ## List all Events
    sql="
  SELECT EVENT_SCHEMA, EVENT_NAME, DEFINER, EVENT_TYPE, LAST_EXECUTED, STATUS
  FROM information_schema.EVENTS
  ORDER BY EVENT_SCHEMA;
  "
    sql_to_file 'List Events' "${sql}" 'mysql_events'

    ## Count of encrypted tables by schema
    sql="
  SELECT TABLE_SCHEMA,
    SUM(CASE
      WHEN CREATE_OPTIONS LIKE \"%ENCRYPTION='Y'%\" THEN 1
        ELSE 0 END) AS Count_Encrypted_Tables,
    SUM(CASE
      WHEN CREATE_OPTIONS NOT LIKE \"%ENCRYPTION='Y'%\" THEN 1
        ELSE 0 END) AS Count_Non_Encrypted_Tables
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA NOT IN ('information_schema', 'performance_schema', 'sys')
    GROUP BY TABLE_SCHEMA;
  "
    sql_to_file 'Encrypted tables count' "${sql}" 'encrypted_tables_count_by_schema'

    ## Default encrypted schemas
    sql="
  SELECT schema_name, default_encryption
  FROM information_schema.SCHEMATA
  WHERE schema_name NOT IN ('information_schema', 'performance_schema');
  "
    sql_to_file 'Default encrypted schemas' "${sql}" 'default_encrypted_schemas'

else

    echo "There are many tables on the server, we skipped the regular MySQL collection queries because they might can cause problems."
fi

## COLLECT PFS if enabled
if grep -i "performance_schema" "${OUT_DIR}/mysql_variables" | grep -i ON > /dev/null 2>&1; then
    echo "*** Performance Schema is enabled ! ***"

    ## Accounts not properly closing connections
    sql="
  SELECT ess.user, ess.host,
    (a.total_connections - a.current_connections) - ess.count_star as not_closed,
    ( (a.total_connections - a.current_connections) - ess.count_star ) * 100 /
    (a.total_connections - a.current_connections) as pct_not_closed
  FROM performance_schema.events_statements_summary_by_account_by_event_name ess
  JOIN performance_schema.accounts a on (ess.user = a.user and ess.host = a.host)
  WHERE ess.event_name = 'statement/com/quit'
    AND (a.total_connections - a.current_connections) > ess.count_star;
  "
    sql_to_file 'Accounts not properly closing connections' "${sql}" 'mysql_pfs_account_not_properly_closing_connections'

    ## Hosts with errors in host_cache
    sql="
  SELECT IP, HOST, COUNT_HOST_BLOCKED_ERRORS
  FROM performance_schema.host_cache
  WHERE COUNT_HOST_BLOCKED_ERRORS > 0;
  "
    sql_to_file 'Hosts with errors in host_cache' "${sql}" 'mysql_pfs_hosts_blocked'

    ## Indexes used vs. unused
    sql="
  SELECT SUM(if(count_star>0,1,0)) IDX_USED, SUM(if(count_star=0,1,0)) IDX_UNUSED
  FROM performance_schema.table_io_waits_summary_by_index_usage
  WHERE index_name IS NOT NULL
  AND index_name NOT LIKE 'PRIMARY' AND object_schema NOT IN ('mysql', 'performance_schema', 'information_schema')
  ORDER BY object_schema, object_name;
  "
    sql_to_file 'Indexes used vs. unused (ingoring PK)' "${sql}" 'mysql_pfs_indexes_used_vs_unused'

    ## List of unused indexes
    sql="
  SELECT object_schema AS \`Schema\`, object_name AS \`Table\`, index_name AS \`Index\`
  FROM performance_schema.table_io_waits_summary_by_index_usage
  WHERE index_name IS NOT NULL
  AND count_star = 0
  AND index_name NOT LIKE 'PRIMARY' AND object_schema NOT IN ('mysql', 'performance_schema', 'information_schema')
  ORDER BY object_schema, object_name;
  "
    sql_to_file 'List of unused indexes' "${sql}" 'mysql_pfs_indexes_unused'

    ## Top 20 statements creating tmp tables to disk
    sql="
  SELECT schema_name, substr(digest_text, 1, 100) AS statement,
  count_star AS cnt, sum_created_tmp_disk_tables AS tmp_disk_tables,
  sum_created_tmp_tables AS tmp_tables
  FROM performance_schema.events_statements_summary_by_digest
  WHERE sum_created_tmp_disk_tables > 0 OR sum_created_tmp_tables > 0
  ORDER BY tmp_disk_tables desc limit 20;
  "
    sql_to_file 'Top 20 statements creating tmp tables to disk' "${sql}" 'mysql_pfs_tmp_to_disk'

    ## Tmp disk tables events/who
    sql="
  SELECT user, host, event_name, count_star AS cnt,
    sum_created_tmp_disk_tables AS tmp_disk_tables
  FROM performance_schema.events_statements_summary_by_account_by_event_name
  WHERE sum_created_tmp_disk_tables  > 0 order by cnt desc;
  "
    sql_to_file 'Tmp disk tables events/who' "${sql}" 'mysql_pfs_tmp_to_disk_event'

    ## Top 20 statements performing full table scans
    sql="
  SELECT schema_name, substr(digest_text, 1, 100) AS statement,
    count_star AS cnt, sum_select_scan AS full_table_scan
  FROM performance_schema.events_statements_summary_by_digest
  WHERE sum_select_scan > 0
  ORDER BY sum_select_scan desc limit 20;
  "
    sql_to_file 'Top 20 statements performing full table scans' "${sql}" 'mysql_pfs_full_scan'

    ## Full table scans events/who
    sql="
  SELECT user, host, event_name, count_star AS cnt, sum_select_scan AS full_table_scan
  FROM performance_schema.events_statements_summary_by_account_by_event_name
  WHERE sum_select_scan > 0 order by cnt desc;
  "
    sql_to_file 'Full table scans events/who' "${sql}" 'mysql_pfs_full_scan_event'

    ## Account which never connected since last start-up
    sql="
  SELECT DISTINCT m_u.user, m_u.host
  FROM mysql.user m_u
  LEFT JOIN performance_schema.accounts ps_a
  ON m_u.user = ps_a.user AND m_u.host = ps_a.host
  WHERE ps_a.user IS NULL
  ORDER BY m_u.user;
  "
    sql_to_file 'Account which never connected since last start-up' "${sql}" 'mysql_pfs_account_never_connect_since_start'

    ## Users which never connected since last start-up
    sql="
  SELECT DISTINCT m_u.user
  FROM mysql.user m_u
  LEFT JOIN performance_schema.users ps_u ON m_u.user = ps_u.user
  WHERE ps_u.user IS NULL
  ORDER BY m_u.user;
  "
    sql_to_file 'Users which never connected since last start-up' "${sql}" 'mysql_pfs_user_never_connect_since_start'

    ## Totally unused account
    ## This P_S query joins against some I_S tables which could cause issues with large numbers of tables
    if [[ ${TOO_MANY_TABLES} -eq 0 ]]; then
        sql="
    SELECT DISTINCT m_u.user, m_u.host
    FROM mysql.user m_u
    LEFT JOIN performance_schema.accounts ps_a
      ON m_u.user = ps_a.user AND ps_a.host = m_u.host
    LEFT JOIN information_schema.views is_v
      ON is_v.DEFINER = CONCAT(m_u.User, '@', m_u.Host) AND is_v.security_type = 'DEFINER'
    LEFT JOIN information_schema.routines is_r ON is_r.DEFINER = CONCAT(m_u.User, '@', m_u.Host) AND is_r.security_type = 'DEFINER'
    LEFT JOIN information_schema.events is_e ON is_e.definer = CONCAT(m_u.user, '@', m_u.host)
    LEFT JOIN information_schema.triggers is_t ON is_t.definer = CONCAT(m_u.user, '@', m_u.host)
    WHERE ps_a.user IS NULL
      AND is_v.definer IS NULL
      AND is_r.definer IS NULL
      AND is_e.definer IS NULL
      AND is_t.definer IS NULL
    ORDER BY m_u.user, m_u.host;
    "
        sql_to_file 'Totally unused account (never connected since last restart and not used to check SP or Views)' "${sql}" 'mysql_pfs_account_tot_not_used'
    fi

    ##Bad queries sum by users
    sql="
  SELECT user, host, event_name,
    sum_created_tmp_disk_tables AS tmp_disk_tables,
    sum_select_full_join AS full_join,
    sum_select_range_check AS range_check,
    sum_sort_merge_passes AS sort_merge,
    sum_sort_scan AS sort_scan,
    sum_select_scan AS full_scan
  FROM performance_schema.events_statements_summary_by_account_by_event_name
  WHERE sum_created_tmp_disk_tables > 0
    OR sum_select_full_join > 0
    OR sum_select_range_check > 0
    OR sum_sort_merge_passes > 0
    OR sum_sort_scan > 0
    OR sum_select_scan > 0
  ORDER BY sum_sort_merge_passes DESC
  LIMIT 20;
  "
    sql_to_file 'Bad queries sum by users (top 20)' "${sql}" 'mysql_pfs_bad_queries_sum'

    ## Collect some additional lock, query information on MySQL8
    if [[ ${MAJOR_VERSION} -eq 8 ]]; then

        sql="
    WITH lock_summary AS (
     SELECT
      owner_thread_id,
      GROUP_CONCAT(
       DISTINCT
       CONCAT(
        LOCK_STATUS, ' ',
        lock_type, ' on ',
        IF(object_type='USER LEVEL LOCK', CONCAT(object_name, ' (user lock)'), CONCAT(OBJECT_SCHEMA, '.', OBJECT_NAME))
       )
       ORDER BY object_type ASC, LOCK_STATUS ASC, lock_type ASC
       SEPARATOR '\n'
      ) AS lock_summary
     FROM performance_schema.metadata_locks
     GROUP BY owner_thread_id
    )
    SELECT ps.*, lock_summary.lock_summary
    FROM sys.processlist ps
    INNER JOIN lock_summary ON ps.thd_id=lock_summary.owner_thread_id\G
    "
        sql_to_file 'MySQL Locks' "${sql}" 'mysql_pfs_locks' "noalign"

        sql="
    SELECT thr.processlist_id AS mysql_thread_id,
         replace(format_pico_time(trx.timer_wait),' ','') AS trx_duration,
         count(CASE WHEN lock_status='GRANTED' THEN 1 ELSE NULL END) AS row_locks_held,
         count(CASE WHEN lock_status='PENDING' THEN 1 ELSE NULL END) AS row_locks_pending,
         group_concat(DISTINCT concat(OBJECT_SCHEMA, '.', object_name)) AS table_with_lock
    FROM performance_schema.events_transactions_current trx
    INNER JOIN performance_schema.threads thr USING (thread_id)
    LEFT JOIN performance_schema.data_locks USING (thread_id)
    GROUP BY thread_id, timer_wait
    ORDER BY timer_wait DESC LIMIT 100;
    "
        sql_to_file 'MySQL Oldest Transactions' "${sql}" 'mysql_pfs_oldest_transactions'

        sql="
    SELECT *, sum_timer_wait / sum(sum_timer_wait) OVER () AS pct
    FROM performance_schema.events_statements_summary_by_digest ORDER BY sum_timer_wait DESC LIMIT 10\G
    "
        sql_to_file 'MySQL Most Time Spent' "${sql}" 'mysql_pfs_most_time_spent' "noalign"

        sql="
    WITH
    histogram AS
      (SELECT digest,
        CASE
          WHEN bucket_timer_low > 10000000000000 THEN '10s'
          WHEN bucket_timer_low > 1000000000000 THEN '1s'
          WHEN bucket_timer_low > 100000000000 THEN '100ms'
          WHEN bucket_timer_low > 10000000000 THEN '10ms'
          WHEN bucket_timer_low > 1000000000 THEN '1ms'
          WHEN bucket_timer_low > 100000000 THEN '100us'
          WHEN bucket_timer_low > 10000000 THEN '10us'
          ELSE '1us'
        END AS bucket_name,
        floor(sum(count_bucket) / sum(sum(count_bucket)) over (partition BY digest)*100) AS pct
      FROM performance_schema.events_statements_histogram_by_digest
      GROUP BY digest, bucket_name),
    ascii AS
      (SELECT digest, group_concat(concat_ws(' ', '\n', bucket_name, ' ', repeat('#',pct)) separator '') AS asciiart
      FROM histogram
      GROUP BY digest)
    SELECT sa.*, ascii.asciiart AS histogram
    FROM sys.statement_analysis sa
    INNER JOIN ascii USING (digest)
    ORDER BY exec_count DESC LIMIT 10\G
    "
        sql_to_file 'MySQL Histogram Top10 running' "${sql}" 'mysql_pfs_histogram' "noalign"

    fi

fi

#############################
# Collect SYS schema tables output
if [[ ${TOO_MANY_TABLES} -eq 0 ]] && { [[ ${MAJOR_VERSION} -eq 8 ]] || { [[ ${MAJOR_VERSION} -eq 5 ]] && [[ ${MINOR_VERSION} -eq 7 ]]; }; }; then

    echo "Collecting SYS schema tables..."

    sys_tables=$("${MYSQLBASEDIR}"/mysql "${DB_CLI_OPTIONS[@]}" -NB --skip-column-names -e"select TABLE_NAME from INFORMATION_SCHEMA.TABLES where TABLE_SCHEMA='sys' and TABLE_NAME not like '%x$%';" 2> /dev/null)

    for systable in ${sys_tables}; do
        if [[ " ${SKIP_SYS_TABLES[*]} " =~ ${systable} ]]; then
            echo "Skipping dangerous sys.${systable} table"
            continue
        fi
        sql="
    SELECT * FROM sys.${systable};
    "
        sql_to_file "sys.${systable}" "${sql}" "sys_${systable}"
    done
fi

#
# Finish up. Compress output.
#
date -u -Iseconds > "${OUT_DIR}/collect_env_end"

if [[ ${SKIPTARRESULT} -eq 0 ]]; then
    echo "Compressing..."
    tar czf "${OUT_DIR}".tgz "${OUT_DIR}" && rm -rf "${OUT_DIR}"
    echo "Filename:" "${OUT_DIR}".tgz
else
    echo "Skipped results compression."
    echo "Directory name:" "${OUT_DIR}"
fi

echo "All tasks finished."
