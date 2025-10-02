#!/bin/sh
#######################################################################################################################
#
#                                   SEP Installer for Docker or Podman
#
#######################################################################################################################
# Supported Operating Systems
#######################################################################################################################
#
#######################################################################################################################
# Required software
#######################################################################################################################
#
#   - docker plus the compose plugin/podman and podman-compose
#   - openssl
#   - sed
#   - yq
#
#   See CHECK_LIST and check_prereqs for more details
#
#######################################################################################################################
# Configuration options
#######################################################################################################################
#
# AUTOSTART         start the stack automatically following a successful installation, default 0
# CONTAINER_ENGINE  specify the container runtime, default docker
# ENABLE_PMM        run PMM as part of the stack, default 1
# INSTALL_DIR       the location for generated files, default ~/sep
# SEP_IMAGE_NAME    the registry address, default docker.io/percona/percona-sep (login required)
# SEP_IMAGE_TAG     the image tag for SEP, default v0.9.0
#
# Additional options that have an effect if set are as follows:
#
# HOST_IP           the IP address that maps to the PMM server, used in containers
#
#######################################################################################################################
# Credentials
#######################################################################################################################
#
# Secrets are for the most part generated and stored in: "${INSTALL_DIR}"/.secrets
#
# This file can be removed after a successfull installation, as it is used whilst generating certain configuration
# and bootstrap files before the stack is created. However, the content of the file should be stored somewhere
# safe, even if it is also left in place.
#
# In addition to the screts used by SEP, you will to login to Docker Hub with a token if using the Percona registry.
# The token will be provided to you by Percona and to use it, simply authenticate before pulling the SEP images, e.g.
#
# $ docker login --username percona docker.io
# Password:
# Login Succeeded!
#
#######################################################################################################################
# Quick start
#######################################################################################################################
#
# The examples will use docker with the compose plugin, simply use podman-compose instead if using podman.
#
# Execute the installer, e.g.
#
#    $ bash -x sep_installer.sh 2>&1 | tee install.log
#
# If AUTOSTART is enabled then simply execute the following to view the logs:
#
#    $ docker compose --file ./sep/compose.yaml --project-name sep logs --follow
#
# Otherwise, first of all execute the following:
#
#    $ docker compose --file ./sep/compose.yaml --project-name sep up --no-recreate --detach
#
#######################################################################################################################
# Troubleshooting and additional information
#######################################################################################################################
#
# Please see the section at the end of this script for more information.
#
#######################################################################################################################
#######################################################################################################################

set -o errexit
set -o nounset

test "${DEBUG:-0}" = 0 || set -o xtrace

AUTOSTART="${AUTOSTART:-0}"
CONTAINER_ENGINE="${CONTAINER_ENGINE:-docker}"
ENABLE_PMM="${ENABLE_PMM:-1}"
INSTALL_DIR="${INSTALL_DIR:-"${HOME}/sep"}"
SEP_IMAGE_NAME="${SEP_IMAGE_NAME:-docker.io/percona/percona-sep}"
SEP_IMAGE_TAG="${SEP_IMAGE_TAG:-v0.9.0}"

test "${ENABLE_PMM}" = "1" || test "${SEP_PMM_URL_AUTH:-undef}" != "undef"

CERTLIST=all-in-one
CHECK_LIST="openssl sed docker podman podman-compose yq"
PROGRESS=0

# shellcheck disable=SC2016
CASDOOR_INIT_JSON_DATA='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
Cf7yN2nEwGGCGwAA'

NGINX_CONFIG='H4sICDtG2mgCA25naW54LmNvbmYA7VOxbtswEN39FTcIyORKQQ3UdsYCRboFAQJ0IxjyZBOheMwd
ldgt8u+lItlqHdvIlg7lRN57j0c+PjY6QrFOKao2rlhbhMJQCGiSo7Cv/ZpAHhZr3foEQ/XqtXhx
AcaT5NXLZCLIT8gD3TtJGGBezaue2qMq6AbBk9F+TZL+ghI9YBCguu7LjKnlAJ+rS+jOKMuyLDpR
wfjYoiTVsjvdeDabgYh/21ydbNrXxSuDnFztjE4IJSZThpULm1IwTjvoU8Tm6hhZPeD2UJBLPf9V
YLzDkFSjN+qe7FaJ+4lwuUM7XzrroRwu043ItNmqqEX2NugYl4uqGpwdSYJJrTG/DsN1Nmp429Ho
o8wf01vUfvr9BrKxDeVbaGv5rOAb8bNmi7abQdEzskptVL2Dutk7N7lhSgSFmDU2eEZztwvpn5E9
w/+6z/KxXB8KGa3jTBkDOGL3bV0ju7AawZdTyVvk8Q8mD5mJc4xWCLPFl7e/alkM54rEB1/s3dnM
exktloiX8//x/PB4/gbqdx6+3wUAAA=='

SEP_COMPOSE_YAML='H4sICETz22gCA2NvbXBvc2UueWFtbADdWN1v2zYQf/dfQXhFH4pSchI3bbn2QYlVx5i/YMnd+iTQ
EmtrkUiNop24Rf73HaVYkWQ5SYclHZYAgu5Tx/vdnUlijFu/oE0YE8QFDQkXTLVa15gmIWZ8E0rB
Y8YVaSFUJtHLmgLIEfpkOa41HXj2+DNBiRTB2leh4F4g/EsmMxUQeZ8GQ5sgM2Abk6+jKOM7tusO
xn1nJ1RxYqZMqZAvU2NL42gXVLB4OK6qTub/wweCXjXF3LNc68xybA+i7g/G8O1EpGopWfpX9s2A
p5hdK0nxCvhp9kFNejmJXtYUMqcYtVMmN0way0gsaGRwEdOAvPh+MXFcbzAlmS5eUsWu6PamvTPS
XCPPlhFyxSSn0T1WEF7KErwR0TpmWWi7V/RSC1LmS1aE9OL7YAz4DIdebzAj2LgxfSZVCmlOPCUu
Gff+vFLeJdsaCYuJSZPEBEZGSPH628NesE/vTG/fH2FJowiHHAvOsGaUXOyoH3eCK8vYEff6qVQb
2S/A3LrFmboS8jLLdhLHJPPHOF1EzAuTzSlBX2mUshq7S5CSa9YCNgT0g0aaS5Wi/kpLdrotXWGh
z6qRhDFdgsquhoSZMOkLTk3QwHlNkpNMs1Q1eUq0RkAVJWYqNxk3EVKVFN51uydEP27jrHSh/puO
Rl7PPpv3CeqUWPbYOhvanjW0Z7rHCTraF55Z57/Np97IGlt9e2SP3UYX48nI6jXau/YQzNzZl0a7
+RTa3Haqsun8bDg496xeb2Y7IDvUZ3dLRqj/yXPs8/ls4H4Bw9Fg7E0tx/l9Mutp+3ukmAZxyG/y
zJXnx6um+QHTR1EJ44xGEEHOKxdeAZguKJ+mgRDyAP4gXYTcvFXCd33SXAQ7vbwQNlSaUbgw4y1M
Q/LttbwqFBsaMTf1Qh4q489UcGLqV0+7yumi/9g1DFlWqqxOp/PI1OynARqqMWnADBYHsgKLklRu
zd2sJ0enB4saiqIPFeL1zgiCKVdnzx17dvejUZeWy8Oxp1md2+MeOCtEN3WbrAytuXvhQUVfTMA2
9SWF9l1RfPzmtBk4PX+roN39jpmZoICvnv033ZPjp8i+ZEGYPgBArvMW6jIJb2uyHt7pydv3TxGe
zyImt542YNXuyaEajGAUeWNrZN+QMse1+jlka5inBLWPOp0joh/t2xJScpuIUO9G8k9kbF/EMeUB
QdjSQRmKppepkSugPAaEcSSWEduw6GPIv4rMLmAJ40HqQfsUiwoWxWuWv3r37pVyvvVp2BYV+4VX
9f3C0yR7waj6uanWEdQTDXTqr1iwBo2P0C80Aire/p/yH/INfFMABBDJ0yBg6t+ZdFWDwEdtGrF4
EfqQZU5j9rEIBa2TpaQBQytGg19RslUrwRGOM9AKLSOmIW8fxKLSxXWuBvvQXC9OBA2wIDT/PDif
zMbZLIZtg5H912TTyQxk7yEZjXOrEDwbyFmh/3yAszDuBTfvyP8+sMeHgD1+XmCLM8PPghTWdy+g
IH8IztJo1HRlIBXcooKfAdzOIXA7zwsuX4b8+oFtUq5zZBxXdkq181n7xXd9hfGHd+G603yd+F3n
XQdOMPBsN+s5O8Vut5sddboVxXPL6U0ms1ul9/B3Q/TzMNC7le7tUPdPDNmqDDiefiUmU35Om5o2
ArPT0ZcbubQ4ODz2BuLOW4n7KC+NtxE1d3v3Ev/oZqLqdO+O4l+tshIYlRNesTPDeqIWvOIqAN6L
g0XLMIzW3+V6HNwwFAAA'
SEP_SETTINGS_YAML='H4sICKDI22gCA3NldHRpbmdzLnlhbWwAzVZNb9s4EL3nVxDdBQwUjeU02W2jU2WJSQjLoktKbbyL
BSHLbOz1h1RRTmEU/u8dilIkOc5ht5cmB1t8o5k3wzcz/g0pWRTL7YPq7+PN+uwsy9P5LimW6VbM
02Qlc/sMIcf36Wfh0sCNGMNBKDjmnNCA26jId7K2wJ64ozzk+hWEztGr1680FIV3IuKYiTH1sG+j
OMv6m3Qu16rvxmqepnmkZA6WQ8cd4cCDQIwLysgtCZ58LYoiU7ZlXbx91x/A/4X9/urqCkDX4R6l
zNjVNAjnEWZAr/e6Z4DJxCeuEwJpEThjbEPe2TkwKVEXs5DcaByLiRPe2cgCyPr3W9HP5MaY+EQn
Tjwb/f6d44kAj0J/PgGHth3HLsPhC7YGNPaQ74SSAEx1hpBgYkpivx8MBqXFDaPwTmNnWfY1/JUY
ZbdOQP46yktXBfuYTU1RhtgJhTeMGLFRlqriIZfq6xpC1Q+2YVmX3xtCETj/TJl3+DCf2X9cXb5t
HHH3Do+dOg4cMjqCu40Y3Gwu50t9Sebzz8t315bJAXxpIx7qCntDGyVyLfO9+JbmIDGhirjQKvKc
0Bk6HNtVaUAAuM25PNYSs9F8Vj60c0aopl3X/VRGxpAy8PGUmFZnEweOSPAJLorWFezyepHZEbdj
dv+B3zOGJzgixLkvtHRviI8rySYybzSr8RGetuCV3FcohP+lc3u6AdHtEC2v5fZRbosU9BNnS/t6
MLgwzaAnTZ0Gwx5h2A1FKXsrjXfFAnprvZ7FycpUJyCTCa6nFfQZ8UPQKL4PcWCGWwXo8dNXCyMc
PyqnEvr7e09XoAcjhicLuYmRu4i3D7L3BvVgzkU+FjUerwuZKw0Al3K+6FOrOXY5h9EARWpZH96g
JgKpEz7hfdnGOgE6SCdGg3TCOHmyWD6eTMEgJ5JoAd00Kl+dAEOo/S5TJwLMSuSZ+1nzQsd7fd7x
7i5kslK7zSn/SRvrhOggnSANcvjHXD6j91Nxhx2v3C3V6vu5PtSdCFuVhI3jSnawbsNqWxh8QmGF
QT/cu37kmUXV0Sh4XjaXbsH6VsdoEauVapBqjTcR6Yjgao9UeyhMV3Jb4SUT3E58GrgtxufVgY0m
4zHfb5Nyq1c9Px43XI/Xnm5qMzXATK8SoVv58AF+FjzKvP+wTmfxur9NN/Fcr/3LlqNPmJGbqYAS
2+hLvFbyGZfxnn/0j9iQ24AyXO0y3iZ2jtRedZ4zmX9J800MDoQqW70Db/bNiDQny21pX/6Gar0Q
OnzET0yz8k7qSaYnYiknpy2muBJL6eKXHtsBHTtew+lnLtkqv74kvZdu/v/34g91ULGmCwsAAA=='

save_progress() {
	test ! -d "${INSTALL_DIR}"/ || printf "%d" "${PROGRESS}" > "${INSTALL_DIR}"/.progress
}

cleanup() {
	echo Done
}

trap 'save_progress' HUP INT QUIT ABRT ALRM TERM
trap 'cleanup' EXIT

generate_secrets() {
	# Create empty file with correct permissions first
	install -m 640 /dev/null "${INSTALL_DIR}"/.secrets

	cat <<-EOS > "${INSTALL_DIR}"/.secrets
	SEP_ORG_CASDOOR_SALT=$(openssl rand -hex 8)
	SEP_ORG_SEP_SALT=$(openssl rand -hex 8)
	SEP_APP_CASDOOR_CLIENT_ID=$(openssl rand -hex 10)
	SEP_APP_CASDOOR_CLIENT_SECRET=$(openssl rand -hex 20)
	SEP_APP_SEP_CLIENT_ID=$(openssl rand -hex 10)
	SEP_APP_SEP_CLIENT_SECRET=$(openssl rand -hex 20)
	SEP_USER_CASDOOR_ADMIN_PASSWD=$(openssl rand -hex 20)
	SEP_USER_SEP_ADMIN_PASSWD=$(openssl rand -hex 20)
	SEP_USER_SEP_USER_PASSWD=$(openssl rand -hex 20)
	SEP_BACKEND_DB_PASSWORD=$(openssl rand -hex 20)
	#
	GF_SECURITY_ADMIN_PASSWORD=$(openssl rand -hex 20)
	INSTALL_DIR=$(realpath "${INSTALL_DIR}")
	EOS
}

get_engine_command() {
	case "${CONTAINER_ENGINE}" in
		docker)
			set +o errexit;
			"${CONTAINER_ENGINE}" compose --file 2>&1 | grep -Fq 'unknown flag: --file' && \
				echo "${CONTAINER_ENGINE}"-compose --file "${INSTALL_DIR}"/compose.yaml --project-name sep || \
				echo "${CONTAINER_ENGINE}" compose --file "${INSTALL_DIR}"/compose.yaml --project-name sep;
			set -o errexit;;
		podman) echo "${CONTAINER_ENGINE}"-compose --file "${INSTALL_DIR}"/compose.yaml --project-name sep;;
		*) return 1
	esac
}

registry_login() {
	echo Checking registry login requirements
	if [ "${SEP_IMAGE_NAME}" = "docker.io/percona/percona-sep" ]; then
		echo Login required, attempting login for "${SEP_IMAGE_NAME}"
		case "${CONTAINER_ENGINE}" in
			docker) "${CONTAINER_ENGINE}" login --username=percona;;
			podman) "${CONTAINER_ENGINE}" login --username=percona --authfile=.docker-io-percona-sep;;
			*) return 1
		esac
	fi
}

needs_context() {
	test -x "$(which sestatus)" || return 0
	return 1
}

set_context() {
	test "${1:-undef}" = undef && return 1
	test -x "$(which semanage)"

	for target in ${1:-}; do
		semanage fcontext -a -t container_ro_file_t "${target}(/.*)?"
	done

	restorecon -irv "${1:-}"
}

# Checkpoints
check_prereqs() {
	# Pre-requisites
	check_prereqs_out=

	for cmd in ${CHECK_LIST}; do
		case "${cmd}" in
			docker) test "${CONTAINER_ENGINE}" = docker || continue;;
			podman|podman-compose) test "${CONTAINER_ENGINE}" = podman || continue;;
		esac
		test -x "$(which "${cmd}")" || check_prereqs_out="${check_prereqs_out} ${cmd}"
	done


	### Example for Oracle Linux 9
	# sudo dnf -y install dnf-plugins-core
	# sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
	# sudo dnf install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

	### Example for Ubuntu 24.04
	# sudo apt-get update
	# sudo apt-get install ca-certificates curl
	# sudo install -m 0755 -d /etc/apt/keyrings
	# sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
	# sudo chmod a+r /etc/apt/keyrings/docker.asc
	# echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
	# sudo apt-get update
	# sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin


	test "${check_prereqs_out}" = "" || {
		printf "ERROR: the following commands are unavailable - %s\n" "${check_prereqs_out}";
		return 1
	}

	PROGRESS=1
}

generate_dirs() {
	install -d "${INSTALL_DIR}" -o "${USER}" -g "${GID:-$(id -g)}" -m 0750
	install -d "${INSTALL_DIR}"/certs -o "${USER}" -g "${GID:-$(id -g)}" -m 0750

	PROGRESS=2
}

generate_tls() {
	generate_secrets

	cd "${INSTALL_DIR}"/certs || exit 3

	find . -type f -perm 0444 -exec chmod -f u+w {} \;

	# Generate JWT for Casdoor
	openssl genpkey -algorithm RSA -out sep_token_jwt_key.key -pkeyopt rsa_keygen_bits:4096
	openssl rsa -pubout -in sep_token_jwt_key.key -out sep_token_jwt_key.pem

	# Generate CA
	openssl ecparam -genkey -name secp384r1 -out sep-ca-key.pem -noout
	openssl req -new -x509 -key sep-ca-key.pem -nodes -out sep-ca.pem \
		-sha384 -days 365 -subj "/CN=SEP Root CA" \
		-addext "keyUsage=critical,digitalSignature,keyCertSign" \
		-addext "basicConstraints=critical,CA:true,pathlen:0" \
		-addext "subjectKeyIdentifier=hash" \
		-addext "authorityKeyIdentifier=keyid:always" \
		-addext "extendedKeyUsage=serverAuth,clientAuth"

	# Generate keys and certificates
	cat <<-EOS > openssl.base.conf
	[ req ]
	distinguished_name = req_distinguished_name
	req_extensions = v3_req

	[ req_distinguished_name ]

	[ v3_req ]
	authorityKeyIdentifier = keyid:always,issuer
	basicConstraints = critical,CA:FALSE
	keyUsage = critical, digitalSignature, keyEncipherment
	extendedKeyUsage = serverAuth, clientAuth
	subjectAltName = @alt_names

	[alt_names]
	EOS

	for cert in $(echo "${CERTLIST}" | tr , " "); do
		cp openssl.base.conf openssl.conf

		# shellcheck disable=SC2183,SC2016
		printf 'DNS.1=localhost\nDNS.2=%s\nDNS.3=%s\nDNS.4=inventory_api\nDNS.5=tasks_api\nDNS.6=app' sep '*.sep' >> openssl.conf
		printf "IP.1=%s\n" 127.0.0.1  >> openssl.conf

		openssl ecparam -genkey -name secp384r1 -out "${cert}-cert-key.pem" -noout
		openssl req -new -key "${cert}-cert-key.pem" -out "${cert}-cert.csr" -subj "/CN=${cert}"
		openssl x509 -req -in "${cert}-cert.csr" -CA sep-ca.pem -CAkey sep-ca-key.pem -CAcreateserial -out "${cert}-cert.pem" -days 365 -sha384 -extfile ./openssl.conf -extensions v3_req

		rm -f "${cert}-cert.csr" openssl.conf
	done

	find . -type f -exec chmod 0444 {} \;

	cd - || exit 3

	PROGRESS=3
}

generate_configs() {
	# shellcheck disable=SC1091
	. "${INSTALL_DIR}"/.secrets

	cat <<-EOS | base64 -d | zcat | sed "s#\${SEP_ORG_CASDOOR_SALT}#${SEP_ORG_CASDOOR_SALT}#; s#\${SEP_ORG_SEP_SALT}#${SEP_ORG_SEP_SALT}#; s#\${SEP_APP_CASDOOR_CLIENT_ID}#${SEP_APP_CASDOOR_CLIENT_ID}#; s#\${SEP_APP_CASDOOR_CLIENT_SECRET}#${SEP_APP_CASDOOR_CLIENT_SECRET}#; s#\${SEP_APP_SEP_CLIENT_ID}#${SEP_APP_SEP_CLIENT_ID}#; s#\${SEP_APP_SEP_CLIENT_SECRET}#${SEP_APP_SEP_CLIENT_SECRET}#; s#\${SEP_USER_CASDOOR_ADMIN_PASSWD}#${SEP_USER_CASDOOR_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_ADMIN_PASSWD}#${SEP_USER_SEP_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_USER_PASSWD}#${SEP_USER_SEP_USER_PASSWD}#; s#\${SEP_IMAGE_NAME}:\${SEP_IMAGE_TAG}#${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}#g; s#\${SEP_BACKEND_DB_PASSWORD}#${SEP_BACKEND_DB_PASSWORD}#g" >"${INSTALL_DIR}"/compose.yaml
	${SEP_COMPOSE_YAML}
	EOS

	test "${ENABLE_PMM}" = "1" || yq -i -y 'del(.services.pmm)' "${INSTALL_DIR}"/compose.yaml

	cat <<-EOS | base64 -d | zcat | sed "s#\${SEP_ORG_CASDOOR_SALT}#${SEP_ORG_CASDOOR_SALT}#; s#\${SEP_ORG_SEP_SALT}#${SEP_ORG_SEP_SALT}#; s#\${SEP_APP_CASDOOR_CLIENT_ID}#${SEP_APP_CASDOOR_CLIENT_ID}#; s#\${SEP_APP_CASDOOR_CLIENT_SECRET}#${SEP_APP_CASDOOR_CLIENT_SECRET}#; s#\${SEP_APP_SEP_CLIENT_ID}#${SEP_APP_SEP_CLIENT_ID}#; s#\${SEP_APP_SEP_CLIENT_SECRET}#${SEP_APP_SEP_CLIENT_SECRET}#; s#\${SEP_USER_CASDOOR_ADMIN_PASSWD}#${SEP_USER_CASDOOR_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_ADMIN_PASSWD}#${SEP_USER_SEP_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_USER_PASSWD}#${SEP_USER_SEP_USER_PASSWD}#; s#\${SEP_IMAGE_NAME}:\${SEP_IMAGE_TAG}#${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}#g; s#\${SEP_BACKEND_DB_PASSWORD}#${SEP_BACKEND_DB_PASSWORD}#g; s#\${SEP_PMM_URL_AUTH}#${SEP_PMM_URL_AUTH}#g" >"${INSTALL_DIR}"/settings.yaml
	${SEP_SETTINGS_YAML}
	EOS

	cat <<-EOS | base64 -d | zcat >"${INSTALL_DIR}"/nginx.conf
	${NGINX_CONFIG}
	EOS

	cat <<-EOS | base64 -d | zcat | sed "s#\${SEP_ORG_CASDOOR_SALT}#${SEP_ORG_CASDOOR_SALT}#; s#\${SEP_ORG_SEP_SALT}#${SEP_ORG_SEP_SALT}#; s#\${SEP_APP_CASDOOR_CLIENT_ID}#${SEP_APP_CASDOOR_CLIENT_ID}#; s#\${SEP_APP_CASDOOR_CLIENT_SECRET}#${SEP_APP_CASDOOR_CLIENT_SECRET}#; s#\${SEP_APP_SEP_CLIENT_ID}#${SEP_APP_SEP_CLIENT_ID}#; s#\${SEP_APP_SEP_CLIENT_SECRET}#${SEP_APP_SEP_CLIENT_SECRET}#; s#\${SEP_USER_CASDOOR_ADMIN_PASSWD}#${SEP_USER_CASDOOR_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_ADMIN_PASSWD}#${SEP_USER_SEP_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_USER_PASSWD}#${SEP_USER_SEP_USER_PASSWD}#g" >"${INSTALL_DIR}"/casdoor_init.json.tmp
	${CASDOOR_INIT_JSON_DATA}
	EOS

	jq --arg SEP_CASDOOR_CERTIFICATE_JSON "$(< "${INSTALL_DIR}"/certs/sep_token_jwt_key.pem)" --arg SEP_CASDOOR_PRIVATE_KEY_JSON "$(< "${INSTALL_DIR}"/certs/sep_token_jwt_key.key)" \
		'.certs[0].certificate = $SEP_CASDOOR_CERTIFICATE_JSON | .certs[0].privateKey = $SEP_CASDOOR_PRIVATE_KEY_JSON' "${INSTALL_DIR}"/casdoor_init.json.tmp >"${INSTALL_DIR}"/casdoor_init.json

	PROGRESS=4
}

generate_stack() {
	$(get_engine_command) up --detach --no-start

	PROGRESS=5
}

start_stack() {
	# shellcheck disable=SC1091
	. "${INSTALL_DIR}"/.secrets

	$(get_engine_command) start
	$(get_engine_command) logs --follow
}

test ! -f "${INSTALL_DIR}"/.progress || PROGRESS="$(cat "${INSTALL_DIR}"/.progress)"

registry_login

test "${PROGRESS}" -gt 0 || check_prereqs  # Errors here will require manual intervention
test "${PROGRESS}" -gt 1 || generate_dirs
test "${PROGRESS}" -gt 2 || generate_tls
test "${PROGRESS}" -gt 3 || generate_configs
test "${PROGRESS}" -gt 4 || generate_stack

echo Setup complete

test "${AUTOSTART}" = "1" || {
        echo "To start the stack, please execute the following command:"
        echo "$(get_engine_command) --file ${INSTALL_DIR}/compose.yaml --project-name sep start"
        echo
        echo "You can follow the progress by executing:"
        echo "$(get_engine_command) --file ${INSTALL_DIR}/compose.yaml --project-name sep logs --follow"
        exit 0
}

start_stack

#######################################################################################################################
# Troubleshooting
#######################################################################################################################
#
# There's surely nothing to go here ;) ... at least right now!
#
#######################################################################################################################
# Additional information
#######################################################################################################################
#
# Useful resources:
# - https://docs.percona.com/pmm/
# - https://docs.percona.com/percona-monitoring-and-management/3/
# - https://docs.percona.com/percona-monitoring-and-management/3/reference/nomad.html
# - https://developer.hashicorp.com/nomad/docs/deploy/production/requirements
# - https://developer.hashicorp.com/nomad/docs/architecture/security
#
#######################################################################################################################
