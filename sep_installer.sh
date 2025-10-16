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
# AUTOSTART            start the stack automatically following a successful installation, default 0
# CONTAINER_ENGINE     specify the container runtime, default docker
# ENABLE_PMM           run PMM as part of the stack, default 1
# INSTALL_DIR          the location for generated files, default ~/sep
# SEP_IMAGE_NAME       the registry address, default docker.io/percona/percona-sep (login required)
# SEP_IMAGE_TAG        the image tag for SEP, default v0.9.2
# SEP_PMM_PUBLIC_HOST  the hostname or IP address that maps to the PMM server, default 127.0.0.1
# SEP_PMM_PORT         the port for PMM. Currently ignored and forced to 443 due to PMM-14382
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
SEP_PMM_PUBLIC_ADDRESS="${SEP_PMM_PUBLIC_HOST:-127.0.0.1}"

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

SEP_SETTINGS_YAML='H4sICD7s52gAA25ldy55YW1sAM1WW2+bSBR+z68YdVeyVDXGabNtw1MxTJJRMLAzkCa7Wo0wntqs
MbBAElmV//ueYSCAQ6S9vDR5sJjvzDnfuc9PqBRVFafrcroPd8nJSV5kq4eoirOUr7JoKwr9BCHD
tt2v3HQdM6AUOz5nmDHiOkxHVfEgWgls8WuX+UxeQegUvXn7RkKBf80DhilfuBa2dRTm+XSXrURS
Ts2wXGVZEZSiAMm5Yd5gxwJDlHGXkiviPOvaVFVe6pp29v7TdAb/Z/rn8/NzAE2DWa5LlVxLgzAW
YAr0Jm8nCvA8m5iGD6S5YyywDn7np8CkRk1MfXIpccw9w7/WkQaQ9udTNc3FTonYRDpOLB39/J1h
j4NGLn+fgUNfjmGTYv8VWQUqefDXc4kDotJDcDBSIdE/z2azWuKSunCnk9M0/QL+asylV4ZDfjvy
S0YF25jeq6DMseFzax5QoqM8K6t1Icq/EjDVfuiKZRt+aw5BYOyrS63Dl9VS/+X8w/tOETOv8cJo
7cAhdW8gtwGFzBZiFcskqd+PHz5daMoH0CWFmC8jbM11FIlEFHv+lBVQYryswkpWkWX4xtxgWG9C
AwWA+5zrY1liOlot64++zwi1tNu4j3mkBF0KOp4dk9XZ2YEj4txCotw2gkNerzI74nbM7l/we8Fw
hCNCjNlclu4lsXFTspEoupqV+A2+78FbsW9QMP9D+/acAT7sEFlecfoo0iqD+gnzWL+Yzc5UM8hJ
07pBsUUoNn1el72WhQ/VBnorSZZhtFXRcYjn4XZaQZ8R24caxXc+dtRwawA5fqblpvli947JgQ6m
twaU/McZxCDK0pWi7dlBPbXQ798nMkITGEEs2ohdiMxNmK7F5B2awBwMbMxbPEwqUZQSAK71/JGn
WndsMgajA4LYkz68Q50F0gZkRHvcxwYGBsjARocMzBhFtIkfR11QyIgTPWDoRqNrYGAOuXnIyxED
yxp5oX7ZXRhob88H2s2NiLblw25Mf9THBiYGyMBIhwzMsDTOc1GhRZiGa1GMGCuVxEtbfWBg6hkY
OpQliYgqZMXhOoXmiSNkhVU4lp/q6WVq1NkwK3B2+ENVMnXv7vk1Nqx6kTZ7/v8NHTl24AlB/E5x
01XwtvCb1ahwz4V9Dc1/Z9qBpbbyoCFBc9xVsAZvlfIYrcJyW3ZI82bpLLo3BDdLs1m6frYVadvn
kgnuOw6N32N82hzoyFss2D6N6idMM+AWi47r8Y6XEwzeO4+imK6TbBkm0zTbhatmCcNVLufjoXff
8IgMaTtZpQisW14/rHzYvk5f+BZTcnnPIQ06+hYmpXjBd7Fnv9pHjMmV41LcLHfWJ3+Kyn05+M5F
8S0rdiEo4GU92wbwbt/tDHUSp7V8/ajsXfANdsNGxnudt3a0yxVRl5zRL7iwKahaxQ+9xxx3YVgd
p2NfRzJqmKYbOP7hyz8oEq0+fa1iXyuG/97CfwPnsr1RLwwAAA=='

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

	cat <<-EOS | base64 -d | zcat | sed "s#\${SEP_ORG_CASDOOR_SALT}#${SEP_ORG_CASDOOR_SALT}#; s#\${SEP_ORG_SEP_SALT}#${SEP_ORG_SEP_SALT}#; s#\${SEP_APP_CASDOOR_CLIENT_ID}#${SEP_APP_CASDOOR_CLIENT_ID}#; s#\${SEP_APP_CASDOOR_CLIENT_SECRET}#${SEP_APP_CASDOOR_CLIENT_SECRET}#; s#\${SEP_APP_SEP_CLIENT_ID}#${SEP_APP_SEP_CLIENT_ID}#; s#\${SEP_APP_SEP_CLIENT_SECRET}#${SEP_APP_SEP_CLIENT_SECRET}#; s#\${SEP_USER_CASDOOR_ADMIN_PASSWD}#${SEP_USER_CASDOOR_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_ADMIN_PASSWD}#${SEP_USER_SEP_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_USER_PASSWD}#${SEP_USER_SEP_USER_PASSWD}#; s#\${SEP_IMAGE_NAME}:\${SEP_IMAGE_TAG}#${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}#g; s#\${SEP_BACKEND_DB_PASSWORD}#${SEP_BACKEND_DB_PASSWORD}#g; s#\${SEP_PMM_URL_AUTH_ACCOUNT}#${SEP_PMM_URL_AUTH_ACCOUNT}#g; s#\${SEP_PMM_URL_AUTH_TOKEN}#${SEP_PMM_URL_AUTH_TOKEN}#g; s#\${SEP_PMM_PORT}#${SEP_PMM_PORT}#g" >"${INSTALL_DIR}"/settings.yaml
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
