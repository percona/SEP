#!/bin/bash
#
# ---
# title: Collect Environment (PostgreSQL)
# description: Collect diagnostic environment data for a PostgreSQL host and store results in an archive.
# parameters:
#   - name: o
#     label: DB CLI options
#     description: Additional arguments passed to the PostgreSQL CLI (e.g. "-h 127.0.0.1 -U postgres").
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
#   - name: s
#     label: Include executed SQL
#     description: Add executed SQL to output files.
#     type: bool
#     arg_format: "-s"
#   - name: w
#     label: Skip WAL statistics
#     description: Do not collect WAL statistics.
#     type: bool
#     arg_format: "-w"
# ---

## Globals
PT_DIRECTORY=".percona-toolkit"
DB_CLI_OPTIONS=()
OUT_DIR=$(hostname)_environment_$(date +%FT%H%M)
if [[ -z "${ISRDS}" ]]; then
  ISRDS=0
fi
PIDTOUSE=""
RUNASROOT=1
SKIPROOTCHECK=1
SKIPTARRESULT=0

## DB Globals
PSQLBIN="/usr/bin/psql"
DB_CLI_OPTIONS+=("-tA")
SQLINOUTPUT=0
COLLECT_WALL_STATS=1
PT_TOOLS=(pt-summary pt-pg-summary)

## Parse arguments
function usage {
  cat << EOF
 Percona Consulting Scripts - v1.3.0
 Usage: $0 [-h] [-o DB arguments] [-d additional string] [-i RDS hostname] [-t] [-r] [-p pid] [-s] [-w]


 GLOBAL OPTIONS:
    -h        Show this message
    -o string Additional arguments to DB CLI (Ex: "-h hostname -u username")
    -d string Additional string add after hostname in output tarball
    -i string Does not collect non-DB related information (for example: disk, mem, cpu). Used in DBaaS like RDS.
              Specify hostname as argument.
    -t        Do not tar the directory after collection is finished
    -r        Run without root privileges (will get permission denied errors)
    -p int    Use this specific PID for DB when multiple instances are running

 PgSQL OPTIONS:
    -s        Add executed SQL to output files
    -w        Do not collect WAL statistics


EOF
}

while getopts hrto:d:i:p:sw flag; do
  case ${flag} in
    o)
      IFS=" " read -r -a OPTS <<< "${OPTARG}";
      for o in "${OPTS[@]}"; do
        DB_CLI_OPTIONS+=("${o}")
      done
      ;;
    d)
      OUTDIRADD="${OPTARG}_";
      OUT_DIR="$(hostname)_${OUTDIRADD}environment_"$(date +%FT%H%M)
      ;;
    i)
      echo "** Will not collect CPU/Disk/Memory stats **"
      ISRDS=1
      OUT_DIR="${OPTARG}_${OPTARG}environment_"$(date +%FT%H%M);
      ;;
    t)
      SKIPTARRESULT=1;
      ;;
    p)
      PIDTOUSE="${OPTARG}"
      ;;
    h)
      usage;
      exit 0;
      ;;
    s)
      echo "** Will add SQL to output files"
      SQLINOUTPUT=1;
      ;;
    w)
      echo "** Will NOT collect WALL statistics"
      COLLECT_WALL_STATS=0;
      ;;
    *)
      usage;
      exit 1;
      ;;
  esac
done

shift $(( OPTIND - 1 ));

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
  for TOOL in pt-summary pt-pg-summary; do
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
  if ! perl "-M${module}" -e 1 2>/dev/null; then
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
  if ! which "${binary}" &>/dev/null; then
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
  elif [[ ${numPids} -gt 1 ]] && [[ -z "${PIDTOUSE}" ]]; then
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
function check_pgsql_connection {
  local result
  result=$(/bin/su postgres -c "echo \"SELECT 1\" | \"${PSQLBIN}\" \"${DB_CLI_OPTIONS[*]}\" 2> /dev/null")
  if [[ "${result}" != "1" ]]; then
    echo "Can't connect to psql using '${PSQLBIN} ${DB_CLI_OPTIONS[*]}'"
    echo "Please confirm connectivity."
    echo ""
    exit 1
  fi
}

# Execute an SQL string and write output into a text file
# @param description, printed to stdout
# @param sql query
# @param new file name
# @param database (use 'global' for non-db-specific queries)
# Example:
# sql_to_file 'Useless list of collations' 'SHOW COLLATIONS' 'collations'
function sql_to_file {
  local stat_desc=$1
  local stat_query=$2
  local stat_file=$3
  local stat_database=${4:-postgres}

  # per-database stats get their own file
  if [[ "${stat_database}" != "global" ]]; then
    stat_file="db_${stat_database}_${stat_file}"
  else
    # if global query, use the postgres database
    stat_database="postgres"
  fi

  echo " - ${stat_desc} (${stat_database})"

  if [[ "${SQLINOUTPUT}" -eq 0 ]]; then
    echo "-----SQL_NOT_INCLUDED=====" > "${OUT_DIR}/${stat_file}"
  else
    # shellcheck disable=SC2086 # Ignore quoting to prevent stat_query from being double parsed
    echo '-----'${stat_query}'=====' > "${OUT_DIR}/${stat_file}"
  fi

  # Script is executed as root. Use 'su' to run SQL under postgres user
  /bin/su postgres -c "echo \"${stat_query}\" | \"${PSQLBIN}\" -d ${stat_database} \"${DB_CLI_OPTIONS[*]}\"" 1>> "${OUT_DIR}/${stat_file}"
}

## Global Pre-flight Checks

# Ensure output directory
mkdir -p "${OUT_DIR}"

# Start
date -u -Iseconds > "${OUT_DIR}/collect_env_start"

# Don't need to be root if RDS
if [[ ${ISRDS} -eq 0 ]] && [[ "$(whoami)" != "root" ]] && [[ "${SKIPROOTCHECK}" -ne 1 ]]; then
  echo "ERROR: $0 must be run by root"
  exit 1
fi

# If not root, and skipping root check, don't run anything requiring root
if [[ "$(whoami)" != "root" ]] && [[ "${SKIPROOTCHECK}" -eq 1 ]]; then
  RUNASROOT=0
fi

set -ue

# check if all tools are available
check_percona_toolkit

# Database connectivity check
check_pgsql_connection

## Database Pre-flight checks

# Any checks that might prevent script should take place here. This is also the location
# to discover any global variables/settings from the DB which will be used later in the script.

# get some PSQL variables we'll need
variables_datadir=$(/bin/su postgres -c "echo \"SHOW data_directory\" | \"${PSQLBIN}\" \"${DB_CLI_OPTIONS[*]}\" 2> /dev/null")

## Main

# Ignore errors and keep collecting
set +e

## System config

if [[ ${ISRDS} -eq 0 ]]; then

  ## Db Sysconfig Pre

  ## Main sysconfig
  echo "Collecting system info... "

  cat /proc/cpuinfo > "${OUT_DIR}/cpuinfo"
  cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > "${OUT_DIR}/scaling_governor" 2>/dev/null
  cpupower frequency-info > "${OUT_DIR}/cpupower_frequency-info" 2>&1
  cat /proc/meminfo > "${OUT_DIR}/meminfo"
  cat /proc/sys/vm/swappiness > "${OUT_DIR}/swappiness"
  "${PT_DIRECTORY}/pt-summary" > "${OUT_DIR}/pt-summary"

  # Some stuff that only can be collected when ran as OS-root
  if [[ "${RUNASROOT}" -eq 1 ]]; then

    sysctl -a > "${OUT_DIR}/sysctl" || true
    dmesg > "${OUT_DIR}/dmesg"

    # Listening tcp ports
    if check_binary ss; then
      ss -nltp >"${OUT_DIR}/tcp_listen_ports"
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
    if ! df "${filename}" &>/dev/null; then
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
    if [[ "${RUNASROOT}" -eq 1 ]]; then
        du -sh "${filename}" >> "${OUT_DIR}/${outfile}"
    fi

    if echo "${datadisk} "| grep 'dm-' >/dev/null 2>&1; then
        pvs | grep "$(lvdisplay | awk '/LV Name/{n=$3} /VG Name/{v=$3} /Block device/{d=$3; sub(".*:","dm-",d); print d,n,v;}' | grep "${datadisk/\/dev\//}" | awk '{print $3}')" | awk '{print $1}' >> "${OUT_DIR}/datadir"
    fi
  }

  ## Db Sysconfig Post
  get_disk_of_file_info "${variables_datadir}" datadir

  echo "Done."
else
  echo "Environment is RDS. Not collecting system info."
fi

## Database Information

echo -n "Executing pt-pg-summary..."
"${PT_DIRECTORY}/pt-pg-summary" -U postgres "${DB_CLI_OPTIONS[*]}" > "${OUT_DIR}/pt-pg-summary"
echo "Done"

echo -n "Collecting PGSQL info... "

## get pgsql version
# MAJOR_VERSION=$(/bin/su postgres -c "echo \"SELECT SUBSTRING(version() FROM '[0-9]+')\" | \"${PSQLBIN}\" \"${OPTIONS[*]}\" 2> /dev/null")
# MINOR_VERSION=$(/bin/su postgres -c "echo \"SELECT RIGHT(SUBSTRING(version() FROM '\.[0-9]+'), -1)\" | \"${PSQLBIN}\" \"${OPTIONS[*]}\" 2> /dev/null")

if [[ "${ISRDS}" -eq 1 ]]; then
  echo "Environment is RDS. Not collecting datadir sizes"
elif [[ -d "${variables_datadir}" ]]; then
  du -sh "${variables_datadir}" >> "${OUT_DIR}/data_usage_raw"
  echo "Done."
else
  echo "Can't find the datadir; Will skip collection raw data info."
fi

#############################
# SQL beautified using https://codebeautify.org/sqlformatter

## Version
sql="
COPY (SELECT (setting::int / 10000)::int, now() FROM pg_settings WHERE name = 'server_version_num') TO stdout WITH (FORMAT csv);
"
sql_to_file 'Version' "${sql}" auditInfo.csv "global"

## database
sql="
COPY (SELECT * FROM pg_database) TO stdout WITH (FORMAT csv);
"
sql_to_file 'Databases' "${sql}" database.csv "global"

## database list
sql="
COPY (SELECT datname FROM pg_database WHERE datistemplate = false AND datallowconn = true) TO stdout WITH (FORMAT text);
"
sql_to_file 'Database list' "${sql}" db_list "global"

# Remove the first line (header) from db_list file, and slurp db list into array
mapfile -t db_list < <(sed '1d' "${OUT_DIR}"/db_list)

# loop over the databases. execute queries for each db.
for db_to_process in "${db_list[@]}"; do

  ## Duplicate indexes
  sql="
  COPY (
  SELECT
    current_database(),
    indrelid::regclass as tablename,
    pg_size_pretty(
    sum(pg_relation_size(idx))::bigint) as size,
    (array_agg(idx)) [1] as idx1,
    (array_agg(idx)) [2] as idx2,
    (array_agg(idx)) [3] as idx3,
    (array_agg(idx)) [4] as idx4
  FROM
    (
    SELECT
      indrelid,
      indexrelid::regclass as idx,
      (indrelid::text || E'\n' || indclass::text || E'\n' || indkey::text || E'\n' || coalesce(indexprs::text, '') || E'\n' || coalesce(indpred::text, '')) as key
    FROM
      pg_index
    ) dups
  GROUP BY
    indrelid,
    key
  HAVING
    count(*) > 1
  ORDER BY
    sum(pg_relation_size(idx)) DESC
  ) TO stdout WITH (FORMAT csv);
  "
  sql_to_file 'Duplicate Indexes' "${sql}" duplicateIndexes.csv "${db_to_process}"

  ## Foreign keys without indexes
  sql="
  COPY (
  SELECT
    current_database(),
    c.conrelid::regclass AS \"table\",
    /* list of key column names in order */
    string_agg(
    a.attname,
    ','
    ORDER BY
      x.n
    ) AS columns,
    pg_catalog.pg_size_pretty(
    pg_catalog.pg_relation_size(c.conrelid)
    ) AS size,
    c.conname AS constraint,
    c.confrelid::regclass AS referenced_table
  FROM
    pg_catalog.pg_constraint c
    /* enumerated key column numbers per foreign key */
    CROSS
    JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS x(attnum, n)
    /* name for each key column */
    JOIN pg_catalog.pg_attribute a ON a.attnum = x.attnum
    AND a.attrelid = c.conrelid
  WHERE
    NOT EXISTS
    /* is there a matching index for the constraint? */
    (
      SELECT 1 FROM pg_catalog.pg_index i
      WHERE
        i.indrelid = c.conrelid
        AND (i.indkey::smallint[])[0:cardinality(c.conkey)- 1] OPERATOR(pg_catalog.@>) c.conkey
    )
    AND c.contype = 'f'
  GROUP BY
    c.conrelid,
    c.conname,
    c.confrelid
  ORDER BY
    pg_catalog.pg_relation_size(c.conrelid) DESC
  ) TO stdout WITH (FORMAT csv);
  "
  sql_to_file 'Foreign Keys without Indexes' "${sql}" foreignKeysWithoutIndexes.csv "${db_to_process}"

  ## Index Bloat
  sql="
  COPY (
  SELECT
    current_database(),
    nspname AS schemaname,
    tblname,
    idxname,
    bs * (relpages)::bigint AS real_size,
    bs * (relpages - est_pages)::bigint AS extra_size,
    100 * (relpages - est_pages)::float / relpages AS extra_ratio,
    fillfactor,
    CASE WHEN relpages > est_pages_ff THEN bs *(relpages - est_pages_ff) ELSE 0 END AS bloat_size,
    100 * (relpages - est_pages_ff)::float / relpages AS bloat_ratio,
    is_na
  FROM
    (
    SELECT
      coalesce(1 + ceil(reltuples / floor((bs - pageopqdata - pagehdr)/(4 + nulldatahdrwidth)::float)),
      0 -- ItemIdData size + computed avg size of a tuple (nulldatahdrwidth)
      ) AS est_pages,
      coalesce(1 + ceil(reltuples / floor((bs - pageopqdata - pagehdr)* fillfactor /(100 *(4 + nulldatahdrwidth)::float))),
      0
      ) AS est_pages_ff,
      bs,
      nspname,
      tblname,
      idxname,
      relpages,
      fillfactor,
      is_na -- , pgstatindex(idxoid) AS pst, index_tuple_hdr_bm, maxalign, pagehdr, nulldatawidth, nulldatahdrwidth, reltuples -- (DEBUG INFO)
    FROM
      (
      SELECT
        maxalign,
        bs,
        nspname,
        tblname,
        idxname,
        reltuples,
        relpages,
        idxoid,
        fillfactor,
        (
        index_tuple_hdr_bm + maxalign - CASE -- Add padding to the index tuple header to align on MAXALIGN
        WHEN index_tuple_hdr_bm % maxalign = 0 THEN maxalign ELSE index_tuple_hdr_bm % maxalign END + nulldatawidth + maxalign - CASE -- Add padding to the data to align on MAXALIGN
        WHEN nulldatawidth = 0 THEN 0 WHEN nulldatawidth::integer % maxalign = 0 THEN maxalign ELSE nulldatawidth::integer % maxalign END
        )::numeric AS nulldatahdrwidth,
        pagehdr,
        pageopqdata,
        is_na -- , index_tuple_hdr_bm, nulldatawidth -- (DEBUG INFO)
      FROM
        (
        SELECT
          n.nspname,
          i.tblname,
          i.idxname,
          i.reltuples,
          i.relpages,
          i.idxoid,
          i.fillfactor,
          current_setting('block_size')::numeric AS bs,
          CASE -- MAXALIGN: 4 on 32bits, 8 on 64bits (and mingw32 ?)
          WHEN version() ~ 'mingw32'
          OR version() ~ '64-bit|x86_64|ppc64|ia64|amd64' THEN 8 ELSE 4 END AS maxalign,
          /* per page header, fixed size: 20 for 7.X, 24 for others */
          24 AS pagehdr,
          /* per page btree opaque data */
          16 AS pageopqdata,
          /* per tuple header: add IndexAttributeBitMapData if some cols are null-able */
          CASE WHEN max(
          coalesce(s.null_frac, 0)
          ) = 0 THEN 2 -- IndexTupleData size
          ELSE 2 + (
          (32 + 8 - 1) / 8
          ) -- IndexTupleData size + IndexAttributeBitMapData size ( max num filed per index + 8 - 1 /8)
          END AS index_tuple_hdr_bm,
          /* data len: we remove null values save space using it fractionnal part from stats */
          sum(
          (
            1 - coalesce(s.null_frac, 0)
          ) * coalesce(s.avg_width, 1024)
          ) AS nulldatawidth,
          max(
          CASE WHEN i.atttypid = 'pg_catalog.name'::regtype THEN 1 ELSE 0 END
          ) > 0 AS is_na
        FROM
          (
          SELECT
            ct.relname AS tblname,
            ct.relnamespace,
            ic.idxname,
            ic.attpos,
            ic.indkey,
            ic.indkey[ic.attpos],
            ic.reltuples,
            ic.relpages,
            ic.tbloid,
            ic.idxoid,
            ic.fillfactor,
            coalesce(a1.attnum, a2.attnum) AS attnum,
            coalesce(a1.attname, a2.attname) AS attname,
            coalesce(a1.atttypid, a2.atttypid) AS atttypid,
            CASE WHEN a1.attnum IS NULL THEN ic.idxname ELSE ct.relname END AS attrelname
          FROM
            (
            SELECT
              idxname,
              reltuples,
              relpages,
              tbloid,
              idxoid,
              fillfactor,
              indkey,
              pg_catalog.generate_series(1, indnatts) AS attpos
            FROM
              (
              SELECT
                ci.relname AS idxname,
                ci.reltuples,
                ci.relpages,
                i.indrelid AS tbloid,
                i.indexrelid AS idxoid,
                coalesce(
                substring(
                  array_to_string(ci.reloptions, ' ')
                  from
                  'fillfactor=([0-9]+)'
                )::smallint,
                90
                ) AS fillfactor,
                i.indnatts,
                pg_catalog.string_to_array(
                pg_catalog.textin(
                  pg_catalog.int2vectorout(i.indkey)
                ),
                ' '
                )::int[] AS indkey
              FROM
                pg_catalog.pg_index i
                JOIN pg_catalog.pg_class ci ON ci.oid = i.indexrelid
              WHERE
                ci.relam =(
                SELECT
                  oid
                FROM
                  pg_am
                WHERE
                  amname = 'btree'
                )
                AND ci.relpages > 0
              ) AS idx_data
            ) AS ic
            JOIN pg_catalog.pg_class ct ON ct.oid = ic.tbloid
            LEFT JOIN pg_catalog.pg_attribute a1 ON ic.indkey[ic.attpos] <> 0
            AND a1.attrelid = ic.tbloid
            AND a1.attnum = ic.indkey[ic.attpos]
            LEFT JOIN pg_catalog.pg_attribute a2 ON ic.indkey[ic.attpos] = 0
            AND a2.attrelid = ic.idxoid
            AND a2.attnum = ic.attpos
          ) i
          JOIN pg_catalog.pg_namespace n ON n.oid = i.relnamespace
          JOIN pg_catalog.pg_stats s ON s.schemaname = n.nspname
          AND s.tablename = i.attrelname
          AND s.attname = i.attname
        GROUP BY
          1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11
        ) AS rows_data_stats
      ) AS rows_hdr_pdg_stats
    ) AS relation_stats
  WHERE
    nspname NOT IN ('pg_catalog', 'information_schema')
  ORDER BY
    nspname, tblname, idxname
  ) to stdout WITH (FORMAT csv);
  "
  sql_to_file 'Index Bloat' "${sql}" indexBloat.csv "${db_to_process}"

  ## Index Bloat v2
  sql="
  COPY (
  SELECT
    current_database(),
    schemaname,
    tablename,
    /*reltuples::bigint, relpages::bigint, otta,*/
    ROUND((CASE WHEN otta = 0 THEN 0.0 ELSE sml.relpages::FLOAT / otta END)::NUMERIC, 1) AS \"table_bloat_pct\",
    CASE WHEN relpages < otta THEN 0 ELSE bs *(sml.relpages - otta)::BIGINT END AS wastedbytes,
    pg_size_pretty(CASE WHEN relpages < otta THEN 0 ELSE bs *(sml.relpages - otta)::BIGINT END) AS table_wasted_size,
    iname AS Index_nam,
    ROUND((CASE WHEN iotta = 0 OR ipages = 0 THEN 0.0 ELSE ipages::FLOAT / iotta END)::NUMERIC, 1) AS \"Index_bloat_pct\",
    CASE WHEN ipages < iotta THEN 0 ELSE bs *(ipages - iotta) END AS wastedibytes,
    pg_size_pretty(CASE WHEN ipages < iotta THEN 0 ELSE bs *(ipages - iotta)::BIGINT END) AS Index_wasted_size
  FROM
    (
    SELECT
      schemaname,
      tablename,
      cc.reltuples,
      cc.relpages,
      bs,
      CEIL(
      (cc.reltuples *((datahdr + ma - (CASE WHEN datahdr % ma = 0 THEN ma ELSE datahdr % ma END))+ nullhdr2 + 4))/(bs - 20::FLOAT)
      ) AS otta,
      COALESCE(c2.relname, '?') AS iname,
      COALESCE(c2.reltuples, 0) AS ituples,
      COALESCE(c2.relpages, 0) AS ipages,
      COALESCE(
      CEIL((c2.reltuples *(datahdr - 12))/(bs - 20::FLOAT)), 0) AS iotta -- very rough approximation, assumes all cols
    FROM
      (
      SELECT
        ma,
        bs,
        schemaname,
        tablename,
        (datawidth + (hdr + ma - (CASE WHEN hdr % ma = 0 THEN ma ELSE hdr % ma END)))::NUMERIC AS datahdr,
        (maxfracsum * (nullhdr + ma - (CASE WHEN nullhdr % ma = 0 THEN ma ELSE nullhdr % ma END))) AS nullhdr2
      FROM
        (
        SELECT
          schemaname,
          tablename,
          hdr,
          ma,
          bs,
          SUM((1 - null_frac)* avg_width) AS datawidth,
          MAX(null_frac) AS maxfracsum,
          hdr +(
          SELECT
            1 + COUNT(*)/ 8
          FROM
            pg_stats s2
          WHERE
            null_frac <> 0
            AND s2.schemaname = s.schemaname
            AND s2.tablename = s.tablename
          ) AS nullhdr
        FROM
          pg_stats s,
          (
          SELECT
            (
            SELECT
              current_setting('block_size')::NUMERIC
            ) AS bs,
            CASE WHEN SUBSTRING(v, 12, 3) IN ('8.0', '8.1', '8.2') THEN 27 ELSE 23 END AS hdr,
            CASE WHEN v ~ 'mingw32' THEN 8 ELSE 4 END AS ma
          FROM
            (
            SELECT
              version() AS v
            ) AS foo
          ) AS constants
        GROUP BY
          1, 2, 3, 4, 5
        ) AS foo
      ) AS rs
      JOIN pg_class cc ON cc.relname = rs.tablename
      JOIN pg_namespace nn ON cc.relnamespace = nn.oid
      AND nn.nspname = rs.schemaname
      AND nn.nspname <> 'information_schema'
      LEFT JOIN pg_index i ON indrelid = cc.oid
      LEFT JOIN pg_class c2 ON c2.oid = i.indexrelid
    ) AS sml
  WHERE
    schemaname != 'pg_catalog'
  ORDER BY
    wastedbytes DESC
  ) to stdout WITH (FORMAT csv);
  "
  sql_to_file 'Index Bloat v2' "${sql}" indexBloatV2.csv "${db_to_process}"

  ## Index Usage
  sql="
  COPY (
  SELECT
    current_database(),
    t.schemaname AS schema,
    t.tablename AS table,
    psai.indexrelname AS index_name,
    pg_table_size(i.indexrelid) AS index_size,
    c.relpages AS pages,
    c.reltuples::bigint AS num_rows,
    psai.idx_scan AS number_of_scans,
    psai.idx_tup_read AS tuples_read,
    psai.idx_tup_fetch AS tuples_fetched
  FROM
    pg_tables t
    LEFT JOIN pg_class c ON t.tablename = c.relname
    LEFT JOIN pg_index i ON c.oid = i.indrelid
    LEFT JOIN pg_stat_all_indexes psai ON i.indexrelid = psai.indexrelid
  WHERE
    t.schemaname NOT IN ('pg_catalog', 'information_schema')
    AND i.indisunique is not true
    AND i.indisprimary is not true
  ORDER BY
    7 DESC NULLS LAST,
    3
  ) to stdout WITH (FORMAT csv);
  "
  sql_to_file 'Index Usage' "${sql}" indexUsage.csv "${db_to_process}"

  ## Invalid Indexes
  sql="
  COPY (
  with table_info as (
    SELECT
    pg_index.indrelid,
    pg_class.oid,
    pg_class.relname as table_name
    from
    pg_class,
    pg_index
    where
    pg_index.indrelid = pg_class.oid
  ),
  t2 AS (
    SELECT
    distinct current_database(),
    pg_index.indexrelid as INDX_ID,
    pg_class.relname as index_name,
    table_info.table_name,
    pg_namespace.nspname as schema_name,
    pg_class.relowner as owner_id,
    pg_index.indisvalid as indx_is_valid
    FROM
    pg_class,
    pg_index,
    pg_namespace,
    table_info
    WHERE
    pg_index.indisvalid = false
    AND pg_index.indexrelid = pg_class.oid
    and pg_class.relnamespace = pg_namespace.oid
    and pg_index.indrelid = table_info.oid
  )
  SELECT
    *
  FROM
    t2
  ) TO stdout WITH (FORMAT csv);
  "
  sql_to_file 'Invalid Indexes' "${sql}" invalidIndexes.csv "${db_to_process}"

  ## Stat User Tables
  sql="
  COPY ( SELECT current_database(),* FROM pg_stat_user_tables ) TO stdout WITH (FORMAT csv);
  "
  sql_to_file 'Stat User Tables' "${sql}" statUserTables.csv "${db_to_process}"

  ## Stat IO User Tables
  sql="
  COPY ( SELECT current_database(), * FROM pg_statio_user_tables ) TO stdout WITH (FORMAT csv);
  "
  sql_to_file 'Stat IO User Tables' "${sql}" statioUserTables.csv "${db_to_process}"

  ## Table Activity
  sql="
  COPY (
  SELECT
    current_database(),
    s.relname,
    s.n_live_tup,
    s.n_mod_since_analyze,
    (s.n_mod_since_analyze::numeric / s.n_live_tup::numeric) * 100 AS percentage_update,
    pg_relation_size(c.oid)
  FROM
    pg_stat_user_tables s,
    pg_class C
  WHERE
    s.n_tup_upd > 0
    AND s.n_live_tup > 0
    AND c.relname = s.relname
  ) TO stdout WITH (FORMAT csv);
  "
  sql_to_file 'Table Activity' "${sql}" tableActivity.csv "${db_to_process}"

  ## Table Bloat
  sql="
  COPY (
  SELECT
    current_database(),
    schemaname,
    tblname,
    bs * tblpages AS real_size,
    (tblpages - est_tblpages)* bs AS extra_size,
    CASE WHEN tblpages - est_tblpages > 0 THEN 100 * (tblpages - est_tblpages)/ tblpages::float ELSE 0 END AS extra_ratio,
    fillfactor,
    CASE WHEN tblpages - est_tblpages_ff > 0 THEN (tblpages - est_tblpages_ff)* bs ELSE 0 END AS bloat_size,
    CASE WHEN tblpages - est_tblpages_ff > 0 THEN 100 * (tblpages - est_tblpages_ff)/ tblpages::float ELSE 0 END AS bloat_ratio,
    is_na
  FROM
    (
    SELECT
      ceil(
      reltuples / (
        (bs - page_hdr) / tpl_size)
      ) + ceil(toasttuples / 4) AS est_tblpages,
      ceil(
      reltuples / (
        (bs - page_hdr) * fillfactor /(tpl_size * 100)
      )
      ) + ceil(toasttuples / 4) AS est_tblpages_ff,
      tblpages,
      fillfactor,
      bs,
      tblid,
      schemaname,
      tblname,
      heappages,
      toastpages,
      is_na
    FROM
      (
      SELECT
        (
        4 + tpl_hdr_size + tpl_data_size + (2 * ma) - CASE WHEN tpl_hdr_size % ma = 0 THEN ma ELSE tpl_hdr_size % ma END - CASE WHEN ceil(tpl_data_size)::int % ma = 0 THEN ma ELSE ceil(tpl_data_size)::int % ma END
        ) AS tpl_size,
        bs - page_hdr AS size_per_block,
        (heappages + toastpages) AS tblpages,
        heappages,
        toastpages,
        reltuples,
        toasttuples,
        bs,
        page_hdr,
        tblid,
        schemaname,
        tblname,
        fillfactor,
        is_na -- , tpl_hdr_size, tpl_data_size
      FROM
        (
        SELECT
          tbl.oid AS tblid,
          ns.nspname AS schemaname,
          tbl.relname AS tblname,
          tbl.reltuples,
          tbl.relpages AS heappages,
          coalesce(toast.relpages, 0) AS toastpages,
          coalesce(toast.reltuples, 0) AS toasttuples,
          coalesce(
          substring(
            array_to_string(tbl.reloptions, ' ')
            FROM
            'fillfactor=([0-9]+)'
          )::smallint,
          100
          ) AS fillfactor,
          current_setting('block_size')::numeric AS bs,
          CASE WHEN version() ~ 'mingw32'
          OR version() ~ '64-bit|x86_64|ppc64|ia64|amd64' THEN 8 ELSE 4 END AS ma,
          24 AS page_hdr,
          23 + CASE WHEN MAX(
          coalesce(s.null_frac, 0)
          ) > 0 THEN (
          7 + count(s.attname)
          ) / 8 ELSE 0::int END + CASE WHEN bool_or(
          att.attname = 'oid'
          and att.attnum < 0
          ) THEN 4 ELSE 0 END AS tpl_hdr_size,
          sum(
          (
            1 - coalesce(s.null_frac, 0)
          ) * coalesce(s.avg_width, 0)
          ) AS tpl_data_size,
          bool_or(
          att.atttypid = 'pg_catalog.name'::regtype
          )
          OR sum(
          CASE WHEN att.attnum > 0 THEN 1 ELSE 0 END
          ) <> count(s.attname) AS is_na
        FROM
          pg_attribute AS att
          JOIN pg_class AS tbl ON att.attrelid = tbl.oid
          JOIN pg_namespace AS ns ON ns.oid = tbl.relnamespace
          LEFT JOIN pg_stats AS s ON s.schemaname = ns.nspname
          AND s.tablename = tbl.relname
          AND s.inherited = false
          AND s.attname = att.attname
          LEFT JOIN pg_class AS toast ON tbl.reltoastrelid = toast.oid
        WHERE
          NOT att.attisdropped
          AND tbl.relkind in ('r', 'm')
        GROUP BY
          1, 2, 3, 4, 5, 6, 7, 8, 9, 10
        ORDER BY
          2, 3
        ) AS s
      ) AS s2
    ) AS s3 -- WHERE NOT is_na
    --   AND tblpages*((pst).free_percent + (pst).dead_tuple_percent)::float4/100 >= 1
  WHERE
    schemaname NOT IN (
    'pg_catalog', 'information_schema'
    )
  ORDER BY
    schemaname,
    tblname
  ) to stdout WITH (FORMAT csv);
  "
  sql_to_file 'Table Bloat' "${sql}" tableBloat.csv "${db_to_process}"

  ## Table sizes
  sql="
  COPY (
  SELECT
    current_database(),
    n.nspname as Schema,
    c.relname as Name,
    pg_catalog.pg_size_pretty (
    pg_catalog.pg_table_size (c.oid)
    ) as Size_Pretty,
    pg_catalog.pg_table_size (c.oid) as Size
  FROM
    pg_catalog.pg_class c
    LEFT JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  WHERE
    c.relkind IN ('r', '')
    AND n.nspname <> 'pg_catalog'
    AND n.nspname <> 'information_schema'
    AND n.nspname NOT LIKE 'pg_toast%'
  ORDER BY
    4 desc, 1, 2
  ) TO stdout WITH (FORMAT csv)
  "
  sql_to_file 'Table Sizes' "${sql}" tableSizes.csv "${db_to_process}"

  ## Unused Indexes
  sql="
  COPY (
  SELECT
    current_database(),
    ai.schemaname,
    ai.relname AS tablename,
    ai.indexrelid as index_oid,
    ai.indexrelname AS indexname,
    i.indisunique,
    ai.idx_scan,
    pg_relation_size(ai.indexrelid) as index_size,
    pg_size_pretty(
    pg_relation_size(ai.indexrelid)
    ) AS pretty_index_size
  FROM
    pg_catalog.pg_stat_all_indexes ai,
    pg_index i
  WHERE
    ai.indexrelid = i.indexrelid
    and ai.idx_scan = 0
    and ai.schemaname not in ('pg_catalog', 'pg_toast')
  order by
    index_size desc
  ) TO stdout WITH (FORMAT csv);
  "
  sql_to_file 'Unused Indexes' "${sql}" unusedIndexes.csv "${db_to_process}"

  ## Extension versions
  sql="
  COPY ( SELECT name, default_version, installed_version from pg_available_extensions WHERE installed_version IS NOT NULL ) TO stdout WITH (FORMAT csv);
  "
  sql_to_file 'Extension versions' "${sql}" extensionVersions.csv "${db_to_process}"

  ## Installed extensions
  sql="
  COPY ( SELECT  * FROM pg_extension ) TO stdout WITH (FORMAT csv);
  "
  sql_to_file 'Installed extentions' "${sql}" installedExtensions.csv "${db_to_process}"

# End db for-loop
done

## Locks
sql="
COPY (SELECT * from pg_locks) TO stdout WITH (FORMAT csv);
"
sql_to_file 'Locks' "${sql}" locks.csv "global"

## Rel Frozen Xid
sql="
COPY (
WITH max_age AS (
  SELECT 2000000000 as max_old_xid, setting AS autovacuum_freeze_max_age
  FROM pg_catalog.pg_settings
  WHERE name = 'autovacuum_freeze_max_age'
),
per_database_stats AS (
  SELECT datname, m.max_old_xid::int, m.autovacuum_freeze_max_age::int, age(d.datfrozenxid) AS oldest_current_xid
  FROM pg_catalog.pg_database d
  JOIN max_age m ON (true)
  WHERE
  d.datallowconn
)
SELECT
  max(oldest_current_xid) AS oldest_current_xid,
  max(ROUND(100 * (oldest_current_xid / max_old_xid::float))) AS percent_towards_wraparound,
  max(ROUND(100 * (oldest_current_xid / autovacuum_freeze_max_age::float))) AS percent_towards_emergency_autovac
FROM
  per_database_stats
) TO stdout WITH (FORMAT csv);
"
sql_to_file 'RelFrozenXid' "${sql}" relFrozenXid.csv "global"

## HBA File Rules
sql="COPY (SELECT * FROM pg_hba_file_rules) TO stdout WITH (FORMAT csv);"
sql_to_file 'HBA File Rules' "${sql}" hbaFileRules.csv "global"

## Roles
sql="
COPY (SELECT * FROM pg_roles) TO stdout WITH (FORMAT csv);
"
sql_to_file 'Roles' "${sql}" roles.csv "global"

sql="
COPY (
  SELECT name, setting, boot_val, sourcefile, context, short_desc, pending_restart, unit
  FROM pg_settings
) TO stdout WITH (FORMAT csv)
"
sql_to_file 'pg_settings' "${sql}" settings.csv "global"

## pg_stat_database
sql="
COPY ( SELECT * FROM pg_stat_database ) TO stdout WITH (FORMAT csv);
"
sql_to_file 'pg_stat_database' "${sql}" statDatabase.csv "global"

## Stat Statements
check=$(/bin/su postgres -c "echo \"SELECT COUNT(1) FROM pg_available_extensions WHERE name = 'pg_stat_statements'\" | \"${PSQLBIN}\" \"${DB_CLI_OPTIONS[*]}\" 2> /dev/null")
if [[ "${check}" -eq 1 ]]; then
  sql="COPY (SELECT * FROM pg_stat_statements
  WHERE dbid = (SELECT datid FROM pg_stat_database where datname = current_database())
  AND query != '<insufficient privilege>') TO stdout WITH (FORMAT csv);
  "
  sql_to_file 'PG Stat Statements' "${sql}" statStatements.csv "global"
else
  echo " - !! pg_stat_statements extension not enabled !!"
fi

## WAL Info
if [[ "${COLLECT_WALL_STATS}" -eq 1 ]]; then
  echo " - !! Collecting WAL activity. This takes 5 minutes to execute. !!"
  sql="
  COPY (
  WITH wal_activity AS (SELECT pg_current_wal_insert_lsn() startof, pg_sleep(300), pg_current_wal_insert_lsn() endof)
  SELECT w.startof, w.endof, pg_wal_lsn_diff(w.endof, w.startof) as growth
  FROM wal_activity w
  ) TO stdout WITH (FORMAT csv);
  "
  sql_to_file 'WAL Info' "${sql}" walinfo.csv "global"
else
  echo " -- !! NOT Collecting WAL activity. !!"
fi

#
# Finish up. Compress output.
#
date -u -Iseconds > "${OUT_DIR}/collect_env_end"

if [[ "${SKIPTARRESULT}" -eq 0 ]]; then
  echo "Compressing..."
  tar czf "${OUT_DIR}".tgz "${OUT_DIR}" && rm -rf "${OUT_DIR}"
  echo "Filename:" "${OUT_DIR}".tgz
else
  echo "Skipped results compression."
  echo "Directory name:" "${OUT_DIR}"
fi

echo "All tasks finished."
