#!/usr/bin/env bash

# ---
# title: "mysql_query_tuning"
# description: "Collects data for MySQL query tuning"
# strict: false
# parameters:
#  - name: defaults-file
#    type: str
#    label: Path to the defaults-file
#    description: Path to MySQL defaults-file
#  - name: query
#    type: str
#    label: Query to tune
#    description: The SQL query to analyze for performance tuning
#    default: ""
#  - name: file
#    type: str
#    label: File, containing the query
#    description: Path to a file containing the SQL query to analyze for performance tuning
#    default: ""
#  - name: database
#    type: str
#    label: Database to use
#    description: Database to use for the query tuning
#    default: ""
#  - name: dest
#    type: str
#    label: Destination for the diagnostic queries file and results
#    description: Path to the directory where the diagnostic queries file and results will be saved
#    default: .$(pwd)/$(hostname)
#  - name: profile
#    type: int
#    label: Profile the query
#    description: If set to 1, the query will be run and additional profiling information will be collected. Not allowed for DML queries. CTE profiled only if option --force is set.
#    default: 0
#  - name: force
#    type: int
#    label: Force profiling
#    description: If set to 1, the query will be profiled even if it is a CTE expression. It is your responsibility to ensure that the query only selects data and does not modify it.
#    default: 0
#  - name: execute
#    type: int
#    label: Execute diagnostic queries
#    description: If set to 1, the diagnostic queries will be executed
#    default: 0
#  - name: help
#    type: int
#    label: Show help message
#    description: Show help message
#    default: 0
# ---

# Usage: ./mysql_query_tuning.sh [--defaults-file=path] --query=query_string|--file=path [--database=name] [--dest=path] [--execute] [--help]
# Example: ./mysql_query_tuning.sh --query="SELECT first_name, last_name FROM actor" --execute --dest=/tmp

declare DEFAULTS_FILE=""
declare QUERY=""
declare FILE=""
declare DATABASE=""
declare DEST="$(pwd)/$(hostname)-$(date +%Y-%m-%d-%H-%M-%S)"
declare PROFILE=0
declare FORCE=0
declare EXECUTE=0

usage() {
   cat << EOS
Usage: $(basename "${0}") [OPTIONS]
Collects data for MySQL query tuning.

This snippet runs set of MySQL queries to collect data for query tuning.
It takes a SQL query as input, either directly or from a file, and writes
diagnostic queries to a file "queries.sql" in the specified destination directory.
If option --execute is set, it will execute the diagnostic queries and write
the results to a file "results.txt". Finally, it will compress the results into a tar.gz file.

Command line options:

   --defaults-file  Path to MySQL defaults-file
   -q, --query      SQL query to analyze for performance tuning
   -f, --file       Path to a file containing the SQL query to analyze
   -D, --database   Database to use for the query tuning
   -d, --dest       Destination directory for the diagnostic queries file and results.
                    Default: $(pwd)/$(hostname)-$(date +%Y-%m-%d-%H-%M-%S)
   -p, --profile    Profile the query.
                    Default: 0
   -F, --force      Force profiling of CTE expressions.
                    Default: 0                    
   -e, --execute    Execute diagnostic queries.
                    Default: 0
   -h, --help       Show this help message

EOS
   exit $1
}

compress_data() {
   tar czf "${DEST}.tar.gz" -C "$(dirname ${DEST})" "$(basename ${DEST})";
}

OPTS=$(getopt --options -q:f:D:d:pFeh --longoptions 'defaults-file:,query:,file:,database:,dest:,profile,force,execute,help' -- "$@")

if [ $? -gt 0 ]; then
   echo "Error parsing options"
   usage 1
fi

eval set -- "$OPTS"

while [[ -n "$*" ]]; do
   case "$1" in
      --defaults-file)
         DEFAULTS_FILE="--defaults-file=$2"
         shift 2
         ;;
      -q | --query)
         QUERY="$2"
         shift 2
         ;;
      -f | --file)
         FILE="$2"
         shift 2
         ;;
      -D | --database)
         DATABASE="$2"
         shift 2
         ;;
      -d | --dest)
         DEST="$2"
         shift 2
         ;;
      -e | --execute)
         EXECUTE=1
         shift 1
         ;;
      -p | --profile)
         PROFILE=1
         shift 1
         ;;
      -F | --force)
         FORCE=1
         shift 1
         ;;
      -h | --help)
         usage
         ;;
      --)
         shift 1
         break
         ;;
      # Need this to catch options mess up that getopt does not recognize
      *)
         echo "Unrecognized option '$1'"
         usage 1
         ;;
   esac
done

if [[ -z "$QUERY" && -z "$FILE" ]] || [[ -n "$QUERY" && -n "$FILE" ]]; then
   echo "Error: Either --query or --file must be specified."
   usage 1
fi

mkdir -p "${DEST}"

if [[ -z "$QUERY" ]]; then
   QUERY=$(cat "$FILE")
   if [ $? -gt 0 ]; then
      echo "Error reading query from file: $FILE, exiting."
      exit 1
   fi
fi

# Remove trailing spaces and semicolon from $QUERY
# We do not care about comments here, so if someone passed
# a query like "SELECT * FROM table; -- comment"
# or "SELECT * FROM table; /* comment */", the trailing comment will not be removed
# As a result, EXPLAIN output will be printed in the horizontal format and other
# formatting issues may occur.
# We may fix this later, but for now we will just remove trailing spaces and semicolon
# and leave comments as they are.
QUERY=$(echo "$QUERY" | sed -e 's/[;[:space:]]*$//')

[ "$SEPDEBUG" ] && echo "Using query: '${QUERY}'"

# We can only define MYSQL command after we have defaults-file
MYSQL="mysql -B $DEFAULTS_FILE"

# 1. Check if the query starts with "SELECT"
# 2. Else, check if the query is DML (INSERT, UPDATE, DELETE)
IS_SELECT=0
IS_DML=0
IS_CTE=0

if [[ $(echo "$QUERY" | head -n 1 | grep -iP '^\s*(/\*.*?\*/)*\s*select(\s|(/\*.*?\*/))') ]]; then
   IS_SELECT=1
elif [[ $(echo "$QUERY" | head -n 1 | grep -iP '^\s*(/\*.*?\*/)*\s*(insert|delete|update)(\s|(/\*.*?\*/))') ]]; then
   IS_DML=1
elif [[ $(echo "$QUERY" | head -n 1 | grep -iP '^\s*(/\*.*?\*/)*\s*with(\s|(/\*.*?\*/))') ]]; then
   IS_CTE=1
else
   echo "Error: The query must start with SELECT, INSERT, UPDATE, DELETE, or WITH."
   exit 1
fi

# These are time-consuming tasks, so we will implement them later
# 3. TODO: Check if we have only one query
# 4. TODO: Check if the query is valid
# 5. TODO: Collect all tables used in the query

# 6. Write safe statements to the query file
QUERY_FILE="${DEST}/queries.sql"
[ "$SEPDEBUG" ] && echo "Writing diagnostic queries to: ${QUERY_FILE}"
echo "-- Diagnostic queries for: ${QUERY}" > "${QUERY_FILE}"
if [[ -n "$DATABASE" ]]; then
   echo "USE ${DATABASE};" >> "${QUERY_FILE}"
fi
echo "EXPLAIN ${QUERY}\G" >> "${QUERY_FILE}"
echo "SHOW WARNINGS \G" >> "${QUERY_FILE}"
echo "EXPLAIN FORMAT=JSON ${QUERY}\G" >> "${QUERY_FILE}"
echo "SHOW WARNINGS \G" >> "${QUERY_FILE}"

# 7. If query is SELECT, write unsafe statements to the query file
if [[ $PROFILE -eq 1 ]]; then
   if [[ $IS_SELECT -eq 1 ]] || [[ $IS_CTE -eq 1 && $FORCE -eq 1 ]]; then
      echo "FLUSH STATUS;" >> "${QUERY_FILE}"
      echo "SET optimizer_trace='enabled=on';" >> "${QUERY_FILE}"
      echo "SET optimizer_trace_max_mem_size=1024*1024*16;" >> "${QUERY_FILE}"
      # We need to manipulate with the session variable profiling_history_size,
      # so that we can guess correct query number in SHOW PROFILES
      echo "SET profiling_history_size=0;" >> "${QUERY_FILE}"
      echo "SET profiling=1;" >> "${QUERY_FILE}"
      echo "SET profiling_history_size=5;" >> "${QUERY_FILE}"
      echo "PAGER md5sum;" >> "${QUERY_FILE}"
      echo "${QUERY};" >> "${QUERY_FILE}"
      echo "NOPAGER;" >> "${QUERY_FILE}"
      echo "SHOW STATUS LIKE 'Handler%';" >> "${QUERY_FILE}"
      echo "SELECT * FROM INFORMATION_SCHEMA.OPTIMIZER_TRACE\G" >> "${QUERY_FILE}"
      echo "SET optimizer_trace='enabled=off';" >> "${QUERY_FILE}"
      echo "SHOW PROFILES;" >> "${QUERY_FILE}"
      echo "SHOW PROFILE FOR QUERY 2;" >> "${QUERY_FILE}"
   fi
fi

# 8. TODO: Collect table statistics and definitions

# 9. If --execute is set, execute the diagnostic queries and write results to results.txt
if [ $EXECUTE -eq 1 ]; then
    [ "$SEPDEBUG" ] && echo "Writing results to: ${DEST}/results.txt"
    $MYSQL < "${QUERY_FILE}" > "${DEST}/results.txt" 2>&1
    if [ $? -gt 0 ]; then
        echo "Error executing diagnostic queries, check results.txt for details."
        exit 1
    fi
fi

# 10. Compress the results into a tar.gz file
[ "$SEPDEBUG" ] && echo "Compressing results to: ${DEST}.tar.gz"
compress_data
