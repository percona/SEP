#!/bin/bash
#
# ---
# title: Collect Environment (Valkey)
# description: Collect diagnostic environment data for a Valkey host and store results in an archive.
# sudo: optional_default_true
# parameters:
#   - name: o
#     label: DB CLI options
#     description: Additional arguments passed to the Valkey CLI (e.g. "-h 127.0.0.1 -p 6379").
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
#   - name: p
#     label: DB PID
#     description: Use this specific PID when multiple instances are running.
#     type: int
#     arg_format: "-p ${value}"
#   - name: l
#     label: Legacy (Redis) mode
#     description: Collect in Redis mode instead of the default Valkey mode.
#     type: bool
#     arg_format: "-l"
#   - name: c
#     label: Cluster mode
#     description: Collect Cluster-related information.
#     type: bool
#     arg_format: "-c"
#   - name: s
#     label: Sentinel mode
#     description: Collect Sentinel-related information.
#     type: bool
#     arg_format: "-s"
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
SKIPROOTCHECK=1
SKIPTARRESULT=0

## DB Globals
REDISMODE=0
CLUSTER=0
SENTINEL=0
SINGLEMODE=0
DB_CLI_OPTIONS+=("--json")
PT_TOOLS=(pt-summary)

## Parse arguments
function usage {
    cat << EOF
 Percona Consulting Scripts - v1.3.0
 Usage: $0 [-h] [-o DB arguments] [-d additional string] [-i RDS hostname] [-t] [-r] [-p pid] [-l] [-c] [-s]


 GLOBAL OPTIONS:
    -h        Show this message
    -o string Additional arguments to DB CLI (Ex: "-h hostname -u username")
    -d string Additional string add after hostname in output tarball
    -i string Does not collect non-DB related information (for example: disk, mem, cpu). Used in DBaaS like RDS.
              Specify hostname as argument.
    -t        Do not tar the directory after collection is finished
    -r        Run without root privileges (will get permission denied errors)
    -p int    Use this specific PID for DB when multiple instances are running

 Valkey OPTIONS:
    -l        Legacy (Redis) mode; Defaults to Valkey mode
    -c        Cluster mode
    -s        Sentinel mode


EOF
}

while getopts hrto:d:i:p:lcs flag; do
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
        l)
            echo "** Redis mode if not specified then Valkey mode **"
            REDISMODE=1
            ;;
        c)
            echo "** Cluster mode **"
            CLUSTER=1
            ;;
        s)
            echo "** Sentinel mode **"
            SENTINEL=1
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
    for TOOL in pt-summary; do
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
function check_valkey_connection {
    local result
    result=$("${DBCLI}" "${DB_CLI_OPTIONS[@]}" ping 2> /dev/null | tail -n1)
    if [[ ! ${result} =~ "PONG" ]]; then
        echo "Can't connect. Check credentials."
        echo ""
        exit 1
    fi
}

# Execute a query and write output into a text file
# @param  description, printed to stdout
# @param  query
# @param  new file name
# @param  append to file
function query_to_file {
    local stat_desc=$1
    local stat_file=$3
    local stat_append=${4:-false}

    # Convert query to array
    IFS=" " read -r -a stat_query <<< "${2}"

    echo " - ${stat_desc}"

    if [[ ${stat_append} == "false" ]]; then
        echo "-----${stat_query[*]}=====" > "${OUT_DIR}"/"${stat_file}"
    else
        echo "-----${stat_query[*]}=====" >> "${OUT_DIR}"/"${stat_file}"
    fi

    # Exec, append, and strip carriage return
    "${DBCLI}" "${DB_CLI_OPTIONS[@]}" "${stat_query[@]}" 2> /dev/null | tr -d '\r' >> "${OUT_DIR}"/"${stat_file}"
}

if [[ -z ${DB_CLI_OPTIONS[*]} ]]; then
    echo "Error: No port set in options"
    exit 1
fi

# set according to Valkey or Redis mode
if [[ ${REDISMODE} -eq 1 ]]; then
    DBCLI=redis-cli
    DBSERVER=redis-server
    DBMODE=redis
else
    DBCLI=valkey-cli
    DBSERVER=valkey-server
    DBMODE=valkey
fi

# check if single instance mode
if [[ ${CLUSTER} -ne 1 ]] && [[ ${SENTINEL} -ne 1 ]]; then
    SINGLEMODE=1
fi

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
check_valkey_connection

## Database Pre-flight checks

# Any checks that might prevent script should take place here. This is also the location
# to discover any global variables/settings from the DB which will be used later in the script.

# If not RDS, check for multiple PIDs
if [[ ${ISRDS} -eq 0 ]]; then
    daemons=(valkey-server redis-server)
    check_pids "${DBSERVER}" "${daemons[@]}"
fi

# Check for jq utility
if ! check_binary jq; then
    echo "!! Please install the 'jq' utility before running $0 !!"
    echo "!! Example: [apt|dnf] install jq !!"
    exit 1
fi

# get RDB location
rdb_filename=$("${DBCLI}" "${DB_CLI_OPTIONS[@]}" CONFIG GET dbfilename 2> /dev/null | jq -r ".dbfilename")
rdb_dirname=$("${DBCLI}" "${DB_CLI_OPTIONS[@]}" CONFIG GET DIR 2> /dev/null | jq -r ".DIR")
rdb_path="${rdb_dirname}/${rdb_filename}"
save_settings=$("${DBCLI}" "${DB_CLI_OPTIONS[@]}" CONFIG GET save 2> /dev/null | jq -r ".save" | tee "${OUT_DIR}/save_settings")

if [[ ${save_settings} == "null" ]]; then
    rdb_enabled="no"
else
    rdb_enabled="yes"
fi

if [[ ${rdb_filename} != "null" ]]; then
    echo "** RDB path: ${rdb_path}"
else
    echo "** RDB file not configured **"
fi

# Get AOF location. The AOF isn't a single file; it has a manifest, base, and multiple incremental files
# All are located inside appenddirname, which is inside 'dir' (rdb_dirname)
aof_enabled=$("${DBCLI}" "${DB_CLI_OPTIONS[@]}" CONFIG GET appendonly 2> /dev/null | jq -r ".appendonly")
if [[ ${aof_enabled} == "yes" ]]; then
    aof_dirname=$("${DBCLI}" "${DB_CLI_OPTIONS[@]}" CONFIG GET appenddirname 2> /dev/null | jq -r ".appenddirname")
    aof_filename=$("${DBCLI}" "${DB_CLI_OPTIONS[@]}" CONFIG GET appendfilename 2> /dev/null | jq -r ".appendfilename")
    aof_path="${rdb_dirname}/${aof_dirname}/${aof_filename}.manifest"
    echo "** AOF path: ${aof_path}"
else
    echo "** AOF is disabled **"
fi

# get the logfile
DBLOG=$("${DBCLI}" "${DB_CLI_OPTIONS[@]}" CONFIG GET logfile 2> /dev/null | jq -r ".logfile")

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
    # get all info related to AOF location
    if [[ ${aof_enabled} == "yes" ]]; then
        get_disk_of_file_info "${aof_path}" aofpath_disk_info
    fi

    # get all info related to RDB location
    if [[ ${rdb_enabled} == "yes" ]]; then
        get_disk_of_file_info "${rdb_path}" rdbpath_disk_info
    fi

    echo "Done."
else
    echo "Environment is RDS. Not collecting system info."
fi

## Database Information

if [[ ${ISRDS} -eq 0 ]]; then

    # Check if the log path is empty
    if [[ ${DBLOG} == "null" ]]; then
        echo "!! Failed to get ${DBMODE} log path !!"
    else
        # Check if the user has permission to access the log file
        if [[ -r ${DBLOG} ]]; then
            tail -n 1000 "${DBLOG}" > "${OUT_DIR}"/"${DBMODE}"_log
            echo "Last 1000 lines of ${DBMODE} log have been saved"
        else
            echo "${DBMODE} log file not accessible: ${DBLOG}. Try running as root?"
        fi
    fi
fi

echo "Collecting ${DBMODE} config info... "

if [[ ${SINGLEMODE} -eq 1 ]]; then
    echo "**Single instance mode**"

    ## config
    query="CONFIG GET *"
    query_to_file 'CONFIG GET' "${query}" "${DBMODE}"_cfg.out

    ## info
    query="INFO all"
    query_to_file 'Info' "${query}" "${DBMODE}"_info.out

    ## hello
    query="HELLO"
    query_to_file 'Hello' "${query}" "${DBMODE}"_hello.out

    ## slowlog
    query="SLOWLOG GET -1"
    query_to_file 'Slow log' "${query}" "${DBMODE}"_slowlog.out

    ## latency latest
    query="LATENCY LATEST"
    query_to_file 'Latency Latest' "${query}" "${DBMODE}"_latlat.out

    ## latency histogram
    query="LATENCY HISTOGRAM"
    query_to_file 'Latency Histogram' "${query}" "${DBMODE}"_lathist.out

    ## latency intrinsic
    query="--intrinsic-latency 1"
    query_to_file 'Intrinsic Latency' "${query}" "${DBMODE}"_latint.out

    ## Big keys
    query="--bigkeys"
    query_to_file 'Big Keys' "${query}" "${DBMODE}"_bigkeys.out

    ## Mem keys
    query="--memkeys"
    query_to_file 'Mem Keys' "${query}" "${DBMODE}"_memkeys.out

    ## Hot keys
    query="--hotkeys"
    query_to_file 'Hot Keys' "${query}" "${DBMODE}"_hotkeys.out
fi

if [[ ${CLUSTER} -eq 1 ]]; then
    echo "** Cluster mode **"

    ## cluster info
    query="CLUSTER INFO"
    query_to_file 'CLUSTER INFO' "${query}" "${DBMODE}"_clu_info.out

    ## cluster nodes
    query="CLUSTER NODES"
    query_to_file 'CLUSTER NODES' "${query}" "${DBMODE}"_clu_nodes.out

    ## cluster shards
    query="CLUSTER SHARDS"
    query_to_file 'CLUSTER SHARDS' "${query}" "${DBMODE}"_clu_shards.out
fi

if [[ ${SENTINEL} -eq 1 ]]; then
    echo "** Sentinel mode **"

    ## sentinel config
    query="SENTINEL CONFIG GET *"
    query_to_file 'SENTINEL CONFIG' "${query}" "${DBMODE}"_sen_cfg.out

    ## sentinel masters
    query="SENTINEL MASTERS"
    query_to_file 'SENTINEL MASTERS' "${query}" "${DBMODE}"_sen_masters.out

    ## sentinel primaries
    query="SENTINEL PRIMARIES"
    query_to_file 'SENTINEL PRIMARIES' "${query}" "${DBMODE}"_sen_primaries.out

    ## following commands per master
    readarray -t masters < <("${DBCLI}" "${DB_CLI_OPTIONS[@]}" -3 --raw -p 26379 SENTINEL MASTERS | grep "name" | awk '{print $2}')
    for master in "${masters[@]}"; do
        echo "master: ${master}"
        ## sentinel replicas
        query="SENTINEL REPLICAS ${master}"
        query_to_file 'SENTINEL REPLICAS' "${query}" "${DBMODE}"_sen_"${master}"_replicas.out

        ## sentinel sentinels
        query="SENTINEL SENTINELS ${master}"
        query_to_file 'SENTINEL SENTINELS' "${query}" "${DBMODE}"_sen_"${master}"_sentinels.out
    done
fi

echo "Collecting 10 seconds of stats..."
query="INFO STATS"
for i in {1..10}; do
    query_to_file "INFO STATS ${i}" "${query}" "${DBMODE}"_stats.out "append"
    sleep 1
done

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
