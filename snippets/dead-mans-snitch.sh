#!/usr/bin/env bash
# vim: noet

set -o errexit -o nounset -o pipefail

declare -r PARAMS_SHORT="s:r:u:h"
declare -r PARAMS_LONG="snitch-id:,rule:,url:,help"
declare -r PMM_ALERT_RULES="graph/api/ruler/grafana/api/v1/rules/"
declare -r PMM_READY_CHECK="v1/readyz"
declare -r PMM_VERSION_CHECK="v1/version"

# TODO: currently, we force the use of netrc
declare -a CURL=(curl --netrc --insecure --silent --header "content-type: application/json; charset=utf-8" --header "accept: application/json" --write-out "%{response_code}\n")

declare OPTS=
declare RULE_NAME=
declare SNITCH_ID=
declare URL="https://127.0.0.1:8443"

usage() {
    local -i exit_code="${1:-0}"

    cat <<- EOS
	Usage: $(basename "${0}") [OPTIONS]

	Checks Dead Man's Snitch alerting

	Command line options:

	   -h, --help        Show this help message

	EOS

    exit ${exit_code}
}

OPTS="$(getopt --options "${PARAMS_SHORT}" --longoptions "${PARAMS_LONG}" -- "${@}")"
eval set -- "${OPTS}"

while [ -n "${*}" ]; do
   case "${1}" in
      -s | --snitch-id)  SNITCH_ID="${2}" ; shift 2 ;;
	  -r | --rule)       RULE_NAME="${2}" ; shift 2 ;;
	  -u | --url)        URL="${2}" ; shift 2 ;;
      -h | --help)       usage ;;
      --)                break ;;
      *)                 echo "Unrecognized option '${1}'" ; usage 1 ;;
   esac
done

test -n "${RULE_NAME}" || { echo Please set the rule name ; usage 11 ; }
test -n "${URL}" || { echo Please set the URL ; usage 11 ; }

test -x "$(which "${CURL[0]}" 2>/dev/null)" || { echo Please install curl ; exit 12 ; }

# Test PMM
"${CURL[@]}" "${URL}/${PMM_READY_CHECK}" --output pmm_readyz.json > pmm_readyz.json.status
"${CURL[@]}" "${URL}/${PMM_VERSION_CHECK}" --output pmm_version.json > pmm_version.json.status

if ! grep -Fq 200 pmm_readyz.json.status; then
    echo ERROR Unable to check PMM readyz
    exit 13
elif ! grep -Fq 200 pmm_version.json.status; then
    echo ERROR Unable to read PMM version, check credentials
    exit 14
fi

if which jq &>/dev/null; then
    if ! jq '.version == .server.version and .version != null' pmm_version.json | grep -Fq true; then
        echo ERROR Unexpected output from PMM version
        jq -cr . pmm_version.json
        exit 15
    fi
fi

# Check alert rules
"${CURL[@]}" "${URL}/${PMM_ALERT_RULES}" --output alert-rules.json > alert-rules.json.status

if ! grep -Fq 200 alert-rules.json.status; then
    echo ERROR Unable to check Grafana rules
    exit 16
fi

echo Checking for "${RULE_NAME}"

jq --arg rule_name "${RULE_NAME}" '.. | objects | select(.title == $rule_name)' alert-rules.json > alert-rules.json.info
grep -Fq "${RULE_NAME}" alert-rules.json.info || exit 17

echo "${RULE_NAME}" alert rule information
cat alert-rules.json.info

echo

# Check nosnch.in
test -n "${SNITCH_ID}" || { echo Done; exit; }

echo Testing connectivity to nosnch.in
"${CURL[0]}" --write-out '%{response_code}\n' --data m="just checking in" "https://nosnch.in/${SNITCH_ID}"
