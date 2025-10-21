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
# SEP_IMAGE_TAG           the image tag for SEP, default v0.9.2
# SEP_PMM_PUBLIC_HOST     the hostname or IP address that maps to the PMM server, default 127.0.0.1
# SEP_PMM_PORT            the port for PMM. Currently ignored and forced to 443 due to PMM-14382
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
#   - SEP_PMM_NOMAD_DATA_DIR=/tmp/sep-pmm-nomad
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
SEP_IMAGE_TAG="${SEP_IMAGE_TAG:-v0.9.2}"
SEP_PMM_PUBLIC_HOST="${SEP_PMM_PUBLIC_HOST:-127.0.0.1}"
SEP_PMM_PUBLIC_ADDRESS="${SEP_PMM_PUBLIC_HOST}"
SEP_PMM_FRONTEND="${SEP_PMM_FRONTEND:-https://${SEP_PMM_PUBLIC_ADDRESS}}"
SEP_PMM_CONTAINER_NAME="${SEP_PMM_CONTAINER_NAME:-sep-pmm-1}"
SEP_PMM_NOMAD_DATA_DIR="${SEP_PMM_NOMAD_DATA_DIR:-/tmp/sep-pmm-nomad}"


# At the moment we have to force 443 due to PMM-14382
#SEP_PMM_PORT="${SEP_PMM_PORT:-443}"
SEP_PMM_PORT="443"

# Only add the port if not 443
if [ "$SEP_PMM_PORT" != "443" ]; then
  SEP_PMM_PUBLIC_ADDRESS="${SEP_PMM_PUBLIC_ADDRESS}:${SEP_PMM_PORT}"
fi

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

SEP_COMPOSE_YAML='H4sICN3o52gAA25ldy55YW1sAN1Y3XPaOBB/56/QcJk8dCqbJDQfmvbBCS5hjq/Bpnd90ghbBTe2
7JMNCc3wv9/KBsc2ENKbS3pzMOOx9kur/e2uJWGMa7+hhRcQJELmERHypFZ7wCzyMBcLT4Yi4CIh
NYSKQ3RcEQA+Qp8NyzaGHWr2vxAUydCdO4kXCuqGzh2XqQiw6OdO1yRId/lCF3PfT+mWadudftva
MJMg0mOeJJ6YxtqSBf7GKXdy2K+yTGr/40eC3u3yuWXYxrVhmRS8bnf6MHcUxslU8vivdE5XxJg/
JJLhGdDjdEI1pNkQHVcEUqMY1WMuF1xqUz+cMF8TYcBccvR4O7Bs2hmSVBZPWcLv2XJV3ygpqpZF
S/NEwqVg/jNa4F7MI7wI/XnAU9c2r+hYMWLuSJ67dPTY6QM+3S5tdUYEayvd4TKJIcwRTcI7Luj3
+4Te8aUW8YDoLIp0IKQDGb7/cdgKdtiT6vr9BZrM97EncCg4VoSCic3o543g0jI2g2ftlLKNbCdg
pl0TPLkP5V0a7SgISGqPCzbxOfWixTlB35gf8wq5SVAi57wGZHDoJ5UUlSUJc2aKs5GtqQzzHF72
xAvYFEQ2ORTqEZdOKJgOEjjLSXKWShayJguJknBZwogey0VKjUKZFASOHi1zSIe9Hh0ORvaKXDab
Zzmzed68IOqxXkSpRNVP6bXM63GboEaBZPaN665Jja45Ug2AoJNt5rVx8/t4SHtG32ibPbNv7zTR
H/SM1k592+yCmj36ulNvPIQeYFpl3nB83e3cUKPVGpkW8AprL3FWa532Z2qZN+NRx/4KrF6nT4eG
Zf0xGLWU7jNczNzAE5mZUmN5t6uxQFtKmIQ+x3xoARmtmJE5kirTHBa7YSj3JAZwJ57Q10L4qYB2
Z8dGLsuQBZO67030YAltkvx4L+8LWbJVoZkq9YSXaN/jUBBdvVJlKhvnhckfoPvyp1kvG43GC0Oz
HQaotJ1BA6I72RMVWJRkcqlvPgLk5HxvQkNXbkMO0NY1QdD+quSxZY6eviZVbjE9VGqpHDf7LTCW
s1ZVnfQ7YIztWwrZfDsA3diRDOp6xvDph/PdwKnGXAbt6QOnp4wcvmr0PzTPTl8j+pK7XnwAgEzm
AvIy8tY5WXXv/Ozi6jXcc7jP5ZIqBV6ungyqTg/aEO0bPXNFihTbaGeQzaHRElQ/aTROiHrU1ymU
yGUUemqbkk2Rkp0wCJhwCcKGckpLWHwXa5kAynxAGPvh1OcL7n/yxLcw1XN5xIUbUyiffFHuJH9N
41et3q1UzvZEO/ZL+UbiXXUj8TrBnnCW/NpQKw+qgYZx7My4OweJT1AvzIdRsPw/xd8TC5gzBAjA
k9dBQFffmXhWgcBBdebzYOI5EGXBAv4pdwXNo6lkLkczzlx0fIyiZTILBcJBClsupwXME/W9aJTq
uEpVcO/r7PlhYQcwCI2/dG4Go37ajWHToKX/Ck9tkAi6gnDs7Fw5481gTlP910OcunEA3qwq//vQ
nu6D9vRtoc0PFL8KVFjfAUhB4hCghQapxqW2lFPzLH4DeBv74G28Lbxi6omHA5ulTOZEOy3tlyrH
t/rRo7rh+JPe2vYwWye+bFw24CAHz/puOWsj2Gw20xNfsyR4Y1itwWC0FrqC34qo536gNyvd2qdu
nxvSVWlwev1GdJ442VhXY83VGw1195Fx8+PDSy8onqwVqC+ysvOyomJu69riH11clI1uXWH8q1lW
AKN0zsv3Z1j11JyW3xTAe368qGmaVvsbzEgJwk8UAAA='

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
    # Ensure the PMM container is running
    if ! "${CONTAINER_ENGINE}" inspect -f '{{.State.Running}}' "${SEP_PMM_CONTAINER_NAME}" 2>/dev/null | grep -q '^true$'; then
        printf "ERROR: container '%s' is not running (engine=%s)\n" "${SEP_PMM_CONTAINER_NAME}" "${CONTAINER_ENGINE}" >&2
        return 1
    fi

    certs_dir_in_cont="/srv/nomad/certs"
    files="nomad-agent-ca.pem global-server-${SEP_PMM_PUBLIC_HOST}.pem global-server-${SEP_PMM_PUBLIC_HOST}-key.pem"

    # Check mandatory cert files inside container
    for f in $files; do
        if ! "${CONTAINER_ENGINE}" exec "${SEP_PMM_CONTAINER_NAME}" test -f "${certs_dir_in_cont}/${f}"; then
            printf "ERROR: missing '%s' inside container at %s\n" "${f}" "${certs_dir_in_cont}" >&2
            return 1
        fi
    done

    # Ensure target certs dir exists
    install -d "${INSTALL_DIR}/certs" -m 0750

    # Copy certs out of the container
    for f in $files; do
        "${CONTAINER_ENGINE}" cp "${SEP_PMM_CONTAINER_NAME}:${certs_dir_in_cont}/${f}" "${INSTALL_DIR}/certs/${f}"
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
    "${CONTAINER_ENGINE}" login --username=percona ${EXTRA_ARGS:+$EXTRA_ARGS}
    "${CONTAINER_ENGINE}" pull "${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}"
    "${CONTAINER_ENGINE}" logout ${EXTRA_ARGS:+$EXTRA_ARGS}
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

	cat <<-EOS | base64 -d | zcat | sed "s#\${SEP_ORG_CASDOOR_SALT}#${SEP_ORG_CASDOOR_SALT}#; s#\${SEP_ORG_SEP_SALT}#${SEP_ORG_SEP_SALT}#; s#\${SEP_APP_CASDOOR_CLIENT_ID}#${SEP_APP_CASDOOR_CLIENT_ID}#; s#\${SEP_APP_CASDOOR_CLIENT_SECRET}#${SEP_APP_CASDOOR_CLIENT_SECRET}#; s#\${SEP_APP_SEP_CLIENT_ID}#${SEP_APP_SEP_CLIENT_ID}#; s#\${SEP_APP_SEP_CLIENT_SECRET}#${SEP_APP_SEP_CLIENT_SECRET}#; s#\${SEP_USER_CASDOOR_ADMIN_PASSWD}#${SEP_USER_CASDOOR_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_ADMIN_PASSWD}#${SEP_USER_SEP_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_USER_PASSWD}#${SEP_USER_SEP_USER_PASSWD}#; s#\${SEP_IMAGE_NAME}:\${SEP_IMAGE_TAG}#${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}#g; s#\${SEP_BACKEND_DB_PASSWORD}#${SEP_BACKEND_DB_PASSWORD}#g; s#\${SEP_PMM_PORT}#${SEP_PMM_PORT}#g; s#\${SEP_PMM_PUBLIC_ADDRESS}#${SEP_PMM_PUBLIC_ADDRESS}#g" >"${INSTALL_DIR}"/compose.yaml
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

CMD="${1:-}"
if [ "${CMD}" = "nomad" ]; then
    cmd_nomad
    exit $?
fi

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
