#!/bin/bash
#
# ---
# title: Collect Environment (MongoDB)
# description: Collect diagnostic environment data for a MongoDB host and store results in an archive.
# parameters:
#   - name: o
#     label: DB CLI options
#     description: Additional arguments passed to the MongoDB CLI (e.g. "--host 127.0.0.1 --username admin").
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
MONGO_SHELL=""
DB_CLI_OPTIONS=(--quiet)
PT_TOOLS=(pt-summary)

## Parse arguments
function usage {
    cat << EOF
 Percona Consulting Scripts - v1.3.0
 Usage: $0 [-h] [-o DB arguments] [-d additional string] [-i RDS hostname] [-t] [-r] [-p pid]

 GLOBAL OPTIONS:
    -h        Show this message
    -o string Additional arguments to DB CLI (Ex: "-h hostname -u username")
    -d string Additional string add after hostname in output tarball
    -i string Does not collect non-DB related information (for example: disk, mem, cpu). Used in DBaaS like RDS.
              Specify hostname as argument.
    -t        Do not tar the directory after collection is finished
    -r        Run without root privileges (will get permission denied errors)
    -p int    Use this specific PID for DB when multiple instances are running

 Mongo OPTIONS:


EOF
}

while getopts hrto:d:i:p: flag; do
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
# Try to run a query and print error if it fails.
function check_mongo_connection {
    local result
    result=$("${MONGO_SHELL}" "${DB_CLI_OPTIONS[@]}" --eval '{ping:1}' | tail -n1)
    if [[ ${result} != "1" ]]; then
        echo "Can't connect to mongodb. Check credentials."
        echo ""
        exit 1
    fi
}

# Execute a query and write output into a text file
# @param  description, printed to stdout
# @param  query
# @param  new file name
function query_to_file {
    local stat_desc=$1
    local stat_query=$2
    local stat_file=$3

    echo " - ${stat_desc}"
    echo "-----${stat_query}=====" > "${OUT_DIR}"/"${stat_file}"
    "${MONGO_SHELL}" "${DB_CLI_OPTIONS[@]}" --eval "${stat_query}" >> "${OUT_DIR}"/"${stat_file}"
}

# Determine mongo client
if command -v mongosh &> /dev/null; then
    MONGO_SHELL="mongosh"
else
    MONGO_SHELL="mongo"
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
check_mongo_connection

## Database Pre-flight checks

# Any checks that might prevent script should take place here. This is also the location
# to discover any global variables/settings from the DB which will be used later in the script.

# If not RDS, check for multiple PIDs
if [[ ${ISRDS} -eq 0 ]]; then
    daemons=(mongod mongos)
    check_pids Mongo "${daemons[@]}"
fi

# Check if we are connecting to a mongos router
IS_MONGOS=$(${MONGO_SHELL} "${DB_CLI_OPTIONS[@]}" --eval 'db.runCommand({ isMaster: 1 }).msg == "isdbgrid"' | tail -n1)

# get some MongoDB variables we'll need
set +e
if [[ ${IS_MONGOS} == "false" ]]; then
    if ! variables_dbpath=$("${MONGO_SHELL}" "${DB_CLI_OPTIONS[@]}" --eval 'db.adminCommand({ getCmdLineOpts: 1 }).parsed.storage.dbPath' 2> /dev/null); then
        echo "WARNING: Cannot find Mongo dbpath"
        variables_dbpath=""
    fi
fi
set -e

VARIABLES_LOG=/var/log/mongodb/mongod.log
"${MONGO_SHELL}" "${DB_CLI_OPTIONS[@]}" --eval 'db.adminCommand({ getCmdLineOpts: 1 }).parsed.systemLog.path' &> /dev/null
if [[ $? -ne 1 ]]; then
    VARIABLES_LOG=$("${MONGO_SHELL}" "${DB_CLI_OPTIONS[@]}" --eval 'db.adminCommand({ getCmdLineOpts: 1 }).parsed.systemLog.path' | tail -n1)
fi

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
    if [[ ${IS_MONGOS} == "false" ]]; then
        get_disk_of_file_info "${variables_dbpath}" dbpath_disk_info
    fi

    echo "Done."
else
    echo "Environment is RDS. Not collecting system info."
fi

## Database Information

if [[ ${ISRDS} -eq 0 ]]; then

    # Check if the log path is empty
    if [[ -z ${VARIABLES_LOG} ]]; then
        echo "Failed to get MongoDB log path from db.adminCommand({getCmdLineOpts: 1})"
        exit 1
    fi

    # Check if the user has permission to access the log file
    if [[ ! -r ${VARIABLES_LOG} ]]; then
        echo "MongoDB log file not accessible: ${VARIABLES_LOG}. Try running as root?"
    else
        tail -n 1000 "${VARIABLES_LOG}" > "${OUT_DIR}/mongo_log"
        echo "Last 1000 lines of MongoDB log have been saved"
    fi
fi

##
echo "Collecting MongoDB config info... "

## serverStatus()
query="JSON.stringify(db.serverStatus(), null, 4);"
query_to_file 'serverStatus' "${query}" 'mongodb_serverStatus'

## list databases
query="JSON.stringify(db.adminCommand({listDatabases:1}), null, 4);"
query_to_file 'list databases' "${query}" 'mongodb_list_databases'

## dbStats()
query="var ldb=db.adminCommand( { listDatabases: 1 } ); for (i=0;i<ldb.databases.length;i++) {  printjson(db.getSiblingDB(ldb.databases[i].name).stats()); print('\n\n') }"
query_to_file 'db stats' "${query}" 'mongodb_dbStats'

## hostInfo
query="JSON.stringify(db.hostInfo(), null, 4);"
query_to_file 'MongoDB Host Info' "${query}" 'mongodb_hostinfo'

## profiling status
query="JSON.stringify(db.getProfilingStatus(), null, 4);"
query_to_file 'Profiling Status' "${query}" 'mongodb_getProfilingStatus'

## getCmdLineOpts
query="JSON.stringify(db.adminCommand({getCmdLineOpts: 1}), null, 4);"
query_to_file 'Command Line Options' "${query}" 'mongodb_getCmdLineOpts'

if [[ ${IS_MONGOS} == "false" ]]; then
    ## replica set configuration
    query="JSON.stringify(rs.conf(), null, 4);"
    query_to_file 'Replica Set Configuration' "${query}" 'mongodb_rs_conf'
    ## replica set status
    query="JSON.stringify(rs.status(), null, 4);"
    query_to_file 'Replica Set Status' "${query}" 'mongodb_rs_status'
    ## oplog stats
    query="JSON.stringify(db.getReplicationInfo(), null, 4);"
    query_to_file 'oplog stats' "${query}" 'mongodb_print_Replication_info'
fi

## list collection per database
query="var ldb=db.adminCommand( { listDatabases: 1 } ); for (i=0;i<ldb.databases.length;i++) {  print('DATABASE ',ldb.databases[i].name); printjson(db.getSiblingDB(ldb.databases[i].name).getCollectionNames()); print('\n\n') }"
query_to_file 'Collections per database' "${query}" 'mongodb_collection_per_database'

## collection stats
query="var ldb=db.adminCommand( { listDatabases: 1 } ); for (i=0;i<ldb.databases.length;i++) { print('DATABASE ',ldb.databases[i].name); printjson(db.getSiblingDB(ldb.databases[i].name).getCollectionInfos()); print('\n\n') }"
query_to_file 'Collection infos per database' "${query}" 'mongodb_collection_infos'

## list collection indexes
query="var ldb = db.adminCommand({ listDatabases: 1 });var excludeDbs = new Set(['admin', 'local', 'config']);for (var i = 0; i < ldb.databases.length; i++) {var dbName = ldb.databases[i].name;if (excludeDbs.has(dbName)) continue;print('\n+++++++++++++++++++++++++++++++++++++++++');print('DATABASE', dbName);print('+++++++++++++++++++++++++++++++++++++++++');var cols = db.getSiblingDB(dbName).getCollectionInfos();for (var j = 0; j < cols.length; j++) {if (cols[j].type !== 'view') {var idx = db.getSiblingDB(dbName).getCollection(cols[j].name).getIndexes(); if (idx.length > 1) {print('\n    ---------------');print('    COLL: ' + cols[j].name);print('    ---------------');}for (var k = 0; k < idx.length; k++) {if (idx[k].name !== '_id_') {print('\n        name: ' + idx[k].name); print('        key: ' + JSON.stringify(idx[k].key));if (idx[k].expireAfterSeconds != null) {print('        expireAfterSeconds: ' + idx[k].expireAfterSeconds);}}}}}}"
query_to_file 'List collection indexes' "${query}" 'mongodb_collection_indexes'

## indexes not used
query="function padRight(string, length) { return string.padEnd(length, ' '); } var ldb = db.adminCommand({ listDatabases: 1 }); print(padRight('Database', 41) + padRight('Collection', 40) + padRight('Index_name', 40) + padRight('Total_accesses', 15)); for (var i = 0; i < ldb.databases.length; i++) { if (ldb.databases[i].name != 'admin' && ldb.databases[i].name != 'config' && ldb.databases[i].name != 'local' && ldb.databases[i].name != 'matl') { var db = db.getSiblingDB(ldb.databases[i].name); var collections = db.getCollectionInfos(); for (var j = 0; j < collections.length; j++) { var collection = collections[j]; var collectionName = collection.name; if (collection.type != 'view' && !collectionName.startsWith('system.')) { var pui = db.runCommand({ aggregate: collectionName, pipeline: [ { \$indexStats: {} }, { \$match: { 'name': { \$nin: ['_id_'] } } }, { \$group: { _id: '\$name', totalAccesses: { \$sum: '\$accesses.ops' } } }, { \$match: { 'totalAccesses': 0 } } ], cursor: { batchSize: 100 } }); if (pui.cursor.firstBatch.length > 0) { for (var k = 0; k < pui.cursor.firstBatch.length; k++) { var indexStat = pui.cursor.firstBatch[k]; var indexName = indexStat._id; if (indexName.length > 30) { indexName = indexName.substring(0, 30) + '...'; } print(padRight(ldb.databases[i].name, 41) + padRight(collectionName, 40) + padRight(indexName, 40) + padRight(indexStat.totalAccesses.toString(), 15)); } } } } } }"
query_to_file 'Index unused' "${query}" 'mongodb_unused_indexes'

## list collection sizes
query="var mgo = db.getMongo(); function getReadableFileSizeString(fileSizeInBytes) { var i = -1; var byteUnits = ['KB','MB','GB','TB','PB','EB','ZB','YB']; do { fileSizeInBytes = fileSizeInBytes / 1024; i++; } while (fileSizeInBytes > 1024); return Math.max(fileSizeInBytes, 0.1).toFixed(1) + byteUnits[i]; }; function getStatsFor(db) { var collectionNames = db.getCollectionInfos(), stats = []; collectionNames.forEach(function(n) { if (n.type != 'view' && !n.name.startsWith('system.') ) { stats.push(db.getCollection(n.name).stats()); } }); stats = stats.sort(function(a, b) { return b['size'] - a['size']; }); for (var c in stats) { print(stats[c]['ns'] + ': ' + getReadableFileSizeString(stats[c]['size']) + ' (' + getReadableFileSizeString(stats[c]['storageSize']) + ')'); } } function getAllStats() { mgo.getDBNames().forEach(function(name) { var db = mgo.getDB(name); print('\n---------------'); printjson(db); print('---------------\n'); if (name != 'admin' && name != 'config' && name != 'local' && name != 'matl' ) { getStatsFor(db) } }) } getAllStats();"
query_to_file 'List collection sizes' "${query}" 'mongodb_list_collections_sizes'

## run-time configuration
query="JSON.stringify(db.adminCommand({getParameter:'*'}), null, 4);"
query_to_file 'Run Time configuration' "${query}" 'mongodb_runtime_configuration'

## connection pool stats
query="JSON.stringify(db.runCommand({connPoolStats : 1 }), null, 4);"
query_to_file 'Connection Pool Stats' "${query}" 'mongodb_connection_pool_stats'

## duplicate indexes
query="var ldb = db.adminCommand( { listDatabases: 1 } ); for ( i = 0; i < ldb.databases.length; i++ )  {     if ( ldb.databases[i].name != 'admin' && ldb.databases[i].name != 'config' && ldb.databases[i].name != 'local' && ldb.databases[i].name != 'matl' ) {           print('DATABASE ',ldb.databases[i].name);         print('+++++++++++++++++++++++++++++++++++++++++');         var db = db.getSiblingDB(ldb.databases[i].name);           var cpd = db.getCollectionInfos();           for ( j = 0; j < cpd.length; j++ ) {                  if ( cpd[j].type != 'view' && cpd[j].name !=  'system.profile' && cpd[j].name !=  'system.views' ) {                  var result = db.runCommand( { listIndexes: cpd[j].name } );  var namespace = result.ns; var indexes = JSON.parse(JSON.stringify(result.cursor.firstBatch));   var indexes2=[];                            for ( k = 0; k < indexes.length; k++ ) {                    indexes2[k] = (((JSON.stringify(indexes[k].key)).replace('{','')).replace('}','')).replace('/,/g' ,'_');                 }                  var founddup = 0;                 for ( k1 = 0; k1 < indexes.length; k1++ ) {                     for ( k2 = 0; k2 < indexes.length; k2++ ) {                       if ( k1 != k2 ) {                          if (indexes2[k1].startsWith(indexes2[k2],0)) { if (founddup == 0) {  print('COLL: '+cpd[j].name); print('---------------'); }                         printjson(indexes[k2]); print(' is the left prefix of:'); printjson(indexes[k1]); print(' and should be dropped:\n\n'+'db.getSiblingDB(\"'+ldb.databases[i].name+'\").runCommand( { dropIndexes: \"' + cpd[j].name + '\", index: \"'+indexes[k2].name+'\" })\n');}}}}}}}}"
query_to_file 'Duplicate Indexes' "${query}" 'mongodb_duplicate_indexes'

## top 10 collections
query="function printTop10CollectionsByDiskSpace(){var allDatabases=db.adminCommand('listDatabases').databases;var allCollections=[];allDatabases.forEach(function(database){var dbName=database.name;var dbCollections=db.getSiblingDB(dbName).getCollectionInfos();dbCollections.forEach(function(collection){if(collection.type !== 'view' && !collection.name.startsWith('system.') && !collection.name.startsWith('replset.')){var stats=db.getSiblingDB(dbName).getCollection(collection.name).stats();var dataSize=stats['size'];var storageSize=stats['storageSize'];var indexSize=stats['totalIndexSize'];var totalSize=storageSize+indexSize;var compressionRatio=(dataSize/storageSize).toFixed(1);allCollections.push({dbName:dbName,collectionName:collection.name,dataSize:dataSize,storageSize:storageSize,compressionRatio:compressionRatio,indexSize:indexSize,totalSize:totalSize})}})});allCollections.sort(function(a,b){return b.totalSize-a.totalSize});print(padRight('Database',41) + padRight('Collection',40) + '                     Data_Size  Storage_Size  Compr_Ratio  Index_Size  Total_Disk_Size');for(var i=0;i<Math.min(10,allCollections.length);i++){var collection=allCollections[i];print(padRight(collection.dbName,40)+' '+padRight(collection.collectionName,60)+' '+padRight(formatBytes(collection.dataSize),14)+padRight(formatBytes(collection.storageSize),14)+padRight(collection.compressionRatio,19)+padRight(formatBytes(collection.indexSize),14)+formatBytes(collection.totalSize))}function formatBytes(bytes,decimals=2){if(bytes===0)return'0 Bytes';const k=1024;const dm=decimals<0?0:decimals;const sizes=['Bytes','KB','MB','GB','TB','PB','EB','ZB','YB'];const i=Math.floor(Math.log(bytes)/Math.log(k));return parseFloat((bytes/Math.pow(k,i)).toFixed(dm))+' '+sizes[i]}function padRight(string,length){return string.padEnd(length,' ')}}printTop10CollectionsByDiskSpace();"
query_to_file 'Top 10 Collections' "${query}" 'mongodb_top10_collections'

## Dataset Size
query="(function(){var mgo=db.getMongo();function getReadableFileSizeString(fileSizeInBytes){var i=-1;var byteUnits=['KB','MB','GB','TB','PB','EB','ZB','YB'];do{fileSizeInBytes/=1024;i++;}while(fileSizeInBytes>1024);return Math.max(fileSizeInBytes,0.1).toFixed(1)+byteUnits[i];}function getAllStats(){var Data_Size=0;var Storage_Size=0;var Compr_ratio=0;var Index_Size=0;var Total_Disk_Size=0;mgo.getDBNames().forEach(function(db){var dbInstance=mgo.getDB(db);mgo.getDB(db).getCollectionInfos().forEach(function(coll){if(coll.type !=='view' && !coll.name.startsWith('system.') && !coll.name.startsWith('replset.') ){var stats=dbInstance.getCollection(coll.name).stats();Data_Size+=stats.size;Storage_Size+=stats.storageSize;Index_Size+=stats.totalIndexSize;}});});Compr_ratio=Data_Size/Storage_Size;Total_Disk_Size=Storage_Size+Index_Size;print('Data_Size Storage_Size Compr_ratio Index_Size Total_Disk_Size');print(getReadableFileSizeString(Data_Size)+'    '+getReadableFileSizeString(Storage_Size)+'       '+Compr_ratio.toFixed(2)+'        '+getReadableFileSizeString(Index_Size)+'     '+getReadableFileSizeString(Total_Disk_Size));}getAllStats();})();"
query_to_file 'Dataset Size' "${query}" 'mongodb_dataset_size'

## Current Operations
query="printjson(db.adminCommand({'currentOp': true}))"
query_to_file 'Current Operations' "${query}" 'mongodb_current_ops'

## sh.status()
if [[ ${IS_MONGOS} == "true" ]]; then
    query="JSON.stringify(sh.status(), null, 4);"
    query_to_file 'Sharding Status' "${query}" 'sh_status'
else
    echo "Skipping collection of sh.status() as I am not connected to a mongos router"
    echo "Collecting 10 seconds of mongotop..."
    mongotop -n10 "${DB_CLI_OPTIONS[@]}" > "${OUT_DIR}"/mongotop
    echo "Collecting 10 seconds of mongostat..."
    mongostat -n10 "${DB_CLI_OPTIONS[@]}" > "${OUT_DIR}"/mongostat
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
