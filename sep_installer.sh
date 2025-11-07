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
#   - nomad (only required if you plan to use the "nomad" helper command to generate a client config)
#
#   See CHECK_LIST and check_prereqs for more details
#
#######################################################################################################################
# Configuration options
#######################################################################################################################
#
# AUTOSTART               start the stack automatically following a successful installation, default 0
# CONTAINER_ENGINE        specify the container runtime, default docker
# ENABLE_PMM              run PMM as part of the stack, default 1
# INSTALL_DIR             the location for generated files, default ~/sep
# SEP_IMAGE_NAME          the registry address, default docker.io/percona/percona-sep (login required)
# SEP_IMAGE_TAG           the image tag for SEP, default v0.9
# SEP_PMM_PUBLIC_HOST     the hostname or IP address that maps to the PMM server, default 127.0.0.1
# SEP_PMM_PORT            the port for PMM, default 8443
# SEP_PMM_FRONTEND        the URL to access PMM, default https://<SEP_PMM_PUBLIC_HOST>
# SEP_PMM_CONTAINER_NAME  the container name for PMM when using the "nomad" command, default sep-pmm-1
# SEP_PMM_NOMAD_DATA_DIR  data dir used in the generated Nomad client config when using the "nomad" command, default /tmp/sep-pmm-nomad
#
# Additional options that have an effect if set are as follows, these should be set before installing as they do not
# use default values:
#
# HOST_IP                   the IP address that maps to the PMM server, used in containers
# SEP_PMM_URL_AUTH_TOKEN    a service account token with admin privileges
# SEP_PMM_URL_AUTH_USER     a user:password string for an admin account to use Nomad via PMM
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
# N.B. if you are using an external PMM then you will need to set the SEP_PMM_URL_AUTH_TOKEN and SEP_PMM_URL_AUTH_USER
#      environment variables; if using ENABLE_PMM=1 then you will need to create a token in PMM, update the
#      settings.yaml and then restart the app container
#
#######################################################################################################################
# Nomad helper command
#######################################################################################################################
#
# You can generate a Nomad *client* configuration that connects to the PMM-hosted Nomad server
# by running the installer with the "nomad" subcommand:
#
#   $ ./sep_installer.sh nomad
#
# Defaults (override via environment variables if needed):
#   - SEP_PMM_CONTAINER_NAME=sep-pmm-1
#   - SEP_PMM_NOMAD_DATA_DIR=${INSTALL_DIR}/nomad_data
#   - SEP_PMM_PUBLIC_HOST=<see main config defaults above>
#
# What the command does:
#   1) Verifies the PMM container "${SEP_PMM_CONTAINER_NAME}" is running using the selected CONTAINER_ENGINE.
#   2) Checks the following files exist inside the container at /srv/nomad/certs/ :
#        - nomad-agent-ca.pem
#        - global-server-${SEP_PMM_PUBLIC_HOST}.pem
#        - global-server-${SEP_PMM_PUBLIC_HOST}-key.pem
#      If any is missing, the command fails with an error.
#   3) Copies those three files to ${INSTALL_DIR}/certs.
#   4) Generates ${INSTALL_DIR}/nomad_client_config.hcl with TLS paths and:
#        data_dir = "${SEP_PMM_NOMAD_DATA_DIR}"
#        client.servers = ["${SEP_PMM_PUBLIC_HOST}:4647"]
#        tls.{ca_file,cert_file,key_file} pointing at the copied certs.
#
# Requirements:
#   - The "nomad" CLI must be installed locally (see Required software above).
#   - The PMM container must be running and must contain the certs listed above at /srv/nomad/certs/.
#
# Common errors:
#   - "container '<name>' is not running": start PMM first (e.g., docker/podman compose up/start) and make sure SEP_PMM_CONTAINER_NAME is set to the correct name .
#   - "missing '<file>' inside container": ensure SEP_PMM_PUBLIC_HOST is set to the correct hostname or IP address used by PMM for Nomad TLS certs.
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
SEP_IMAGE_TAG="${SEP_IMAGE_TAG:-v0.9}"
SEP_PMM_PUBLIC_HOST="${SEP_PMM_PUBLIC_HOST:-127.0.0.1}"
SEP_PMM_PORT="${SEP_PMM_PORT:-8443}"
SEP_PMM_FRONTEND="${SEP_PMM_FRONTEND:-https://${SEP_PMM_PUBLIC_HOST}}"
SEP_PMM_NOMAD_DATA_DIR="${SEP_PMM_NOMAD_DATA_DIR:-${INSTALL_DIR}/nomad_data}"

test "${ENABLE_PMM}" = "1" || \
	test "${SEP_PMM_URL_AUTH_TOKEN:-undef}" != "undef" || \
	test "${SEP_PMM_URL_AUTH_USER:-undef}" != "undef"

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

SEP_COMPOSE_YAML='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'

SEP_SETTINGS_YAML='H4sICJo99mgAA2N1cnJlbnQueWFtbADNVm1vm0gQ/p5fseqdZKlqjNPm2oZPxbBJVsHA7UKa3Om0
wnhrc8bAAUlkVf7vN8tCAIdI9/KlyQeLeWZnnnnZmf0JlaKq4nRdTvfhLjk5yYts9RBVcZbyVRZt
RaGfIGTYtvuVm65jBpRix+cMM0Zch+moKh5Eq4Etfu0yn8kjCJ2iN2/fSCjwr3nAMOUL18K2jsI8
n+6ylUjKqRmWqywrglIUoDk3zBvsWOCIMu5SckWcZ1ubqspLXdPO3n+azuD/TP98fn4OoGkwy3Wp
0mtpEMYCTIHe5O1EAZ5nE9PwgTR3jAXWIe78FJjUqImpTy4ljrln+Nc60gDS/nyqprnYKRWbyMCJ
paOfvzPscbDI5e8zcOjrMWxS7L+iq0ClD/F6LnFAVUYIAUYqJfrn2WxWa1xSF850epqmX8Bfjbn0
ynDIb0dxyaxgG9N7lZQ5NnxuzQNKdJRnZbUuRPlXAq7aD12xbNNvzSEJjH11qXX4slrqv5x/eN8Z
YuY1XhitHxBS9wZqG1CobCFWsSyS+v344dOFpmIAW1KJ+TLD1lxHkUhEsedPWQEtxssqrGQXWYZv
zA2G9SY10AC4z7kWyxbT0WpZf/RjRqil3eZ9LCKl6FKw8RyY7M7OD4iIcwuFctsMDnm9yuyI2zG7
f8HvBcMRjggxZnPZupfExk3LRqLoelbiN/i+B2/FvkHB/Q8d23MF+PCGyPaK00eRVhn0T5jH+sVs
dqYug5w0bRgUW4Ri0+d122tZ+FBt4G4lyTKMtio7DvE83E4ruGfE9qFH8Z2PHTXcGkCOn2m5ab7Y
vWNyoIPprQEt/3EGOYiydKVoe3ZQTy30+/eJzNAERhCLNmIXInMTpmsxeYcmMAcDG/MWD5NKFKUE
gGs9f6RU68QmYzA6IIk97cM71HkgbUJGrMd9bOBggAx8dMjAjVFEm/hxNASFjATRA4ZhNLYGDuZQ
m4e8HHGwrJEX5pfdgYH1Vj6wbm5EtC0fdmP2oz42cDFABk46ZOCGpXGeiwotwjRci2LEWak0Xvrq
AwNXz8AwoCxJRFQhKw7XKVyeOEJWWIVj9ameXpZGyYZVAdnhD9XJ1L2759fYsOpF2uz5/zd05NiB
JwTxO8PNrYK3hd+sRoV7LuxruPx3ph1YaisPLiRYjrsO1uCtUh6jVVhuyw5p3iydR/eG4GZpNkvX
z7Yibe+5ZIJ7gXuLBa93MQykdsj1ZWq6yfHQi+u0EejyONunUf3QacbgYtFFdPwSkHMOXkWPopiu
k2wZJtM024UrvfMrp+ihd97wiEx8nxosZV4/v3zY0U5f+RZTcnnPoVg6+hYmpXjBd7Fnv9pHjMmV
41LcPAFYn/wpKvfl4DsXxbes2IVggJf1BBzAu323WZQkTmv9+unZO+Ab7IaNLIG6uu0CkIukbkyj
35Zh03a1iR962znuwrA6TsexjlTUME03cPzDl3/QJFotfa2vX2uG/37R/wY8oYWmVQwAAA=='

cmd_nomad() {
    certs_dir_in_cont="/srv/nomad/certs"
    files="nomad-agent-ca.pem global-server-${SEP_PMM_PUBLIC_HOST}.pem global-server-${SEP_PMM_PUBLIC_HOST}-key.pem"

    # Check mandatory cert files inside container
    for f in $files; do
        $(get_engine_command) exec pmm sh -c "test -f '${certs_dir_in_cont}/${f}' || { echo 'ERROR: missing ${f} inside container at ${certs_dir_in_cont}'; exit 1; }" || return 1
    done

    # Ensure target certs dir exists
    install -d "${INSTALL_DIR}/certs" -m 0750

    # Copy certs out of the container
    for f in $files; do
        $(get_engine_command) cp "pmm:${certs_dir_in_cont}/${f}" "${INSTALL_DIR}/certs/${f}"
        chmod 0644 "${INSTALL_DIR}/certs/${f}" || true
    done

    # Compute paths for the config template
    SEP_PMM_NOMAD_CA_PATH="${INSTALL_DIR}/certs/nomad-agent-ca.pem"
    SEP_PMM_NOMAD_CERT_PATH="${INSTALL_DIR}/certs/global-server-${SEP_PMM_PUBLIC_HOST}.pem"
    SEP_PMM_NOMAD_CERT_KEY_PATH="${INSTALL_DIR}/certs/global-server-${SEP_PMM_PUBLIC_HOST}-key.pem"

    # Write Nomad client config
    cat > "${INSTALL_DIR}/nomad_client_config.hcl" <<EOF
log_level = "DEBUG"

data_dir = "${SEP_PMM_NOMAD_DATA_DIR}"

server {
  enabled = false
}

client {
  enabled = true
  servers = ["${SEP_PMM_PUBLIC_HOST}:4647"]
  artifact {
    disable_filesystem_isolation = true
  }
}

tls {
  http = true
  rpc  = true

  ca_file   = "${SEP_PMM_NOMAD_CA_PATH}"
  cert_file = "${SEP_PMM_NOMAD_CERT_PATH}"
  key_file  = "${SEP_PMM_NOMAD_CERT_KEY_PATH}"

  verify_server_hostname = true
  verify_https_client    = true
}

plugin "raw_exec" {
  config {
      enabled = true
  }
}
EOF

    printf "Nomad client config written to: %s\n" "${INSTALL_DIR}/nomad_client_config.hcl"
    printf "Start a Nomad client with:\n  nomad agent -config \"%s/nomad_client_config.hcl\"\n" "${INSTALL_DIR}"
}


save_progress() {
	test ! -d "${INSTALL_DIR}"/ || printf "%d" "${PROGRESS}" > "${INSTALL_DIR}"/.progress
}

cleanup() {
	echo Done
}

usage() {
	cat <<'EOF'
SEP Installer for Docker or Podman

USAGE
  ./sep_installer.sh [COMMAND]
  ./sep_installer.sh --help | -h | help

COMMANDS
  (no command)   Run the default install flow (checks, generate certs/configs, compose up).
  nomad          Generate a Nomad *client* config pointing to the PMM-hosted Nomad server.

ENVIRONMENT (common)
  AUTOSTART                Start the stack after install (default: 0)
  CONTAINER_ENGINE         Container runtime: docker|podman (default: docker)
  ENABLE_PMM               Run PMM as part of the stack (default: 1)
  INSTALL_DIR              Output directory (default: ~/sep)
  SEP_IMAGE_NAME           Image registry (default: docker.io/percona/percona-sep)
  SEP_IMAGE_TAG            SEP image tag (default: v0.9)
  SEP_PMM_PUBLIC_HOST      PMM public host/IP (default: 127.0.0.1)
  SEP_PMM_PORT             PMM port (default: 8443)
  SEP_PMM_FRONTEND         PMM URL (default: https://${SEP_PMM_PUBLIC_HOST})

ENVIRONMENT (nomad command)
  SEP_PMM_CONTAINER_NAME   PMM container name to inspect/copy from (default: sep-pmm-1)
  SEP_PMM_NOMAD_DATA_DIR   Nomad client data dir in generated config (default: ${INSTALL_DIR}/nomad_data)

EXAMPLES
  # Default install flow
  ./sep_installer.sh

  # Show logs after install
  docker compose --file ./sep/compose.yaml --project-name sep logs --follow

  # Generate Nomad client config, copying certs from the running PMM container
  ./sep_installer.sh nomad

  # Start a local Nomad client (after 'nomad' command above)
  nomad agent -config "${HOME}/sep/nomad_client_config.hcl"
EOF
}


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
	SEP_PMM_URL_AUTH_ACCOUNT=${SEP_PMM_URL_AUTH_ACCOUNT:-admin:admin}
	SEP_PMM_URL_AUTH_TOKEN=${SEP_PMM_URL_AUTH_TOKEN:-CHANGEME}
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

pull_sep_image_if_registry_login_required() {
	echo Checking registry login requirements
	if [ "${SEP_IMAGE_NAME}" = "docker.io/percona/percona-sep" ]; then
		echo Login required, attempting login for "${SEP_IMAGE_NAME}"
		EXTRA_ARGS=
    if [ "${CONTAINER_ENGINE}" = "podman" ]; then
        EXTRA_ARGS="--authfile=.docker-io-percona-sep"
    fi
    "${CONTAINER_ENGINE}" login --username=percona ${EXTRA_ARGS:+$EXTRA_ARGS} "${SEP_IMAGE_NAME%%/*}"
    "${CONTAINER_ENGINE}" pull "${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}"
    "${CONTAINER_ENGINE}" logout ${EXTRA_ARGS:+$EXTRA_ARGS} "${SEP_IMAGE_NAME%%/*}"
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

	cat <<-EOS | base64 -d | zcat | sed "s#\${SEP_ORG_CASDOOR_SALT}#${SEP_ORG_CASDOOR_SALT}#; s#\${SEP_ORG_SEP_SALT}#${SEP_ORG_SEP_SALT}#; s#\${SEP_APP_CASDOOR_CLIENT_ID}#${SEP_APP_CASDOOR_CLIENT_ID}#; s#\${SEP_APP_CASDOOR_CLIENT_SECRET}#${SEP_APP_CASDOOR_CLIENT_SECRET}#; s#\${SEP_APP_SEP_CLIENT_ID}#${SEP_APP_SEP_CLIENT_ID}#; s#\${SEP_APP_SEP_CLIENT_SECRET}#${SEP_APP_SEP_CLIENT_SECRET}#; s#\${SEP_USER_CASDOOR_ADMIN_PASSWD}#${SEP_USER_CASDOOR_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_ADMIN_PASSWD}#${SEP_USER_SEP_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_USER_PASSWD}#${SEP_USER_SEP_USER_PASSWD}#; s#\${SEP_IMAGE_NAME}:\${SEP_IMAGE_TAG}#${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}#g; s#\${SEP_BACKEND_DB_PASSWORD}#${SEP_BACKEND_DB_PASSWORD}#g; s#\${SEP_PMM_PORT}#${SEP_PMM_PORT}#g; s#\${SEP_PMM_PUBLIC_ADDRESS}#${SEP_PMM_PUBLIC_HOST}#g" >"${INSTALL_DIR}"/compose.yaml
	${SEP_COMPOSE_YAML}
	EOS

	test "${ENABLE_PMM}" = "1" || yq -i -y 'del(.services.pmm)' "${INSTALL_DIR}"/compose.yaml

	cat <<-EOS | base64 -d | zcat | sed "s#\${SEP_ORG_CASDOOR_SALT}#${SEP_ORG_CASDOOR_SALT}#; s#\${SEP_ORG_SEP_SALT}#${SEP_ORG_SEP_SALT}#; s#\${SEP_APP_CASDOOR_CLIENT_ID}#${SEP_APP_CASDOOR_CLIENT_ID}#; s#\${SEP_APP_CASDOOR_CLIENT_SECRET}#${SEP_APP_CASDOOR_CLIENT_SECRET}#; s#\${SEP_APP_SEP_CLIENT_ID}#${SEP_APP_SEP_CLIENT_ID}#; s#\${SEP_APP_SEP_CLIENT_SECRET}#${SEP_APP_SEP_CLIENT_SECRET}#; s#\${SEP_USER_CASDOOR_ADMIN_PASSWD}#${SEP_USER_CASDOOR_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_ADMIN_PASSWD}#${SEP_USER_SEP_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_USER_PASSWD}#${SEP_USER_SEP_USER_PASSWD}#; s#\${SEP_IMAGE_NAME}:\${SEP_IMAGE_TAG}#${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}#g; s#\${SEP_BACKEND_DB_PASSWORD}#${SEP_BACKEND_DB_PASSWORD}#g; s#\${SEP_PMM_URL_AUTH_ACCOUNT}#${SEP_PMM_URL_AUTH_ACCOUNT}#g; s#\${SEP_PMM_URL_AUTH_TOKEN}#${SEP_PMM_URL_AUTH_TOKEN}#g; s#\${SEP_PMM_PORT}#${SEP_PMM_PORT}#g; s#\${SEP_PMM_FRONTEND}#${SEP_PMM_FRONTEND}#g" >"${INSTALL_DIR}"/settings.yaml
	${SEP_SETTINGS_YAML}
	EOS

	cat <<-EOS | base64 -d | zcat >"${INSTALL_DIR}"/nginx.conf
	${NGINX_CONFIG}
	EOS

	cat <<-EOS | base64 -d | zcat | sed "s#\${SEP_ORG_CASDOOR_SALT}#${SEP_ORG_CASDOOR_SALT}#; s#\${SEP_ORG_SEP_SALT}#${SEP_ORG_SEP_SALT}#; s#\${SEP_APP_CASDOOR_CLIENT_ID}#${SEP_APP_CASDOOR_CLIENT_ID}#; s#\${SEP_APP_CASDOOR_CLIENT_SECRET}#${SEP_APP_CASDOOR_CLIENT_SECRET}#; s#\${SEP_APP_SEP_CLIENT_ID}#${SEP_APP_SEP_CLIENT_ID}#; s#\${SEP_APP_SEP_CLIENT_SECRET}#${SEP_APP_SEP_CLIENT_SECRET}#; s#\${SEP_USER_CASDOOR_ADMIN_PASSWD}#${SEP_USER_CASDOOR_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_ADMIN_PASSWD}#${SEP_USER_SEP_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_USER_PASSWD}#${SEP_USER_SEP_USER_PASSWD}#g" >"${INSTALL_DIR}"/casdoor_init.json.tmp
	${CASDOOR_INIT_JSON_DATA}
	EOS

	# shellcheck disable=SC3034
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

# ---- command-line dispatcher (global) ----------------------------------------
CMD="${1:-}"
case "${CMD}" in
	-h|--help|help)
		usage
		exit 0
		;;
	nomad)
		cmd_nomad
		exit $?
		;;
	"") ;;
	*)
		printf "Unknown command: %s\n" "${CMD}" >&2
		printf "Use --help to see usage.\n" >&2
		exit 2
		;;
esac

# ---- main flow ----------------------------------------------------------------
trap 'save_progress' HUP INT QUIT ABRT ALRM TERM
trap 'cleanup' EXIT

test ! -f "${INSTALL_DIR}"/.progress || PROGRESS="$(cat "${INSTALL_DIR}"/.progress)"

pull_sep_image_if_registry_login_required

test "${PROGRESS}" -gt 0 || check_prereqs  # Errors here will require manual intervention
test "${PROGRESS}" -gt 1 || generate_dirs
test "${PROGRESS}" -gt 2 || generate_tls
test "${PROGRESS}" -gt 3 || generate_configs
test "${PROGRESS}" -gt 4 || generate_stack

echo Setup complete

test "${AUTOSTART}" = "1" || {
        echo "To start the stack, please execute the following command:"
        echo "$(get_engine_command) start"
        echo
        echo "You can follow the progress by executing:"
        echo "$(get_engine_command) logs --follow"
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
