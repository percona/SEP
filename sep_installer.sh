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
# Additional options that have an effect if set are as follows, these should be set before installing:
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
SEP_IMAGE_TAG="${SEP_IMAGE_TAG:-v0.9.0}"

test "${ENABLE_PMM}" = "1" || \
	test "${SEP_PMM_URL_AUTH_TOKEN:-undef}" != "undef" || \
	test "${SEP_PMM_URL_AUTH_USER:-undef}" != "undef"

CERTLIST=all-in-one
CHECK_LIST="openssl sed docker podman podman-compose yq"
PROGRESS=0
SEP_PMM_PORT=443  # Forced for the time being

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

SEP_COMPOSE_YAML='H4sIAAAAAAACA91YW3ObOBR+96/QeDN96BRwEjdNtc0DianjWd/G4O72iZFBtWlAokJ24mby3/cI
DDEYJ+nOJtnZZMaDzo2j8306SNI0rfEbWgURRoyTADNOZaNxo5E40ChbBYKziDKJGwhtD9GbigHo
Efps2o457rnW8AtGseD+0pMBZ67PvSsqUhNQuZ97fQsjw6crgy3DMJXbluP0hl07V8ooNhIqZcDm
ib4mUZgn5c8ez6tsk8b/9Amjt3U5d0zHPDdty4Wsu70hvDvmiZwLmvxI3+mzRKM3UhBtAfIkfaEa
utkQvakYpEE11EyoWFGhz0M+I6HOeER8fHB7ObIdtzfGqa02J5Jek/VdM3dSUj2rlh4wSQUj4QNe
kF5CY23Fw2VE09TyR/RGKRLqCVqkdHDbGwI+/b7b6U2wpt8ZHhUygTLHruRXlLnfr6V7Rdd6TCNs
kDg2QJAOBH/38/EomkfuXTfPT/AkYagFTOOMakqwFSIf/XoQrTSNfPBgnBLb8C4BM+8Go/Kai6u0
2nEU4TQeZWQWUjeIVycYfSNhQiviNkZSLGkDxJDQLzopKZGSeAulyW0bimGBR8uZBBGZg0nOIW7E
VHicEQMstIyT+Di13GJNVhJl4RNJsJGIVSqNuZBbBge3tjV2x4OBOx5NnDt82m4fF8r2SfsDVj+b
SZSWqPpTfh3rfNrFqLUlsobmed9yzb41UQ0Ao8Nd5bl58cd07A7Modm1BtbQqQ0xHA3MTq2/Y/XB
zZl8rfWbjqEHWHZZN56e93sXrtnpTCwbdPsWIa4UZROi+9m1rYvppOd8hRiD3tAdm7b952jSUaEe
0GrEjwKWhSn1mbd1fQa6lCQC2h4JIZlMtk3QAlhFPI8kPudiD09AOwuYsTHS7tdTPVlyu4wwKyKM
MJgZ0Rq6Jv75TlxvkWZnwWaubsACqX9POMOGenRVqGxcrFN6A82Y3r/1tNVqPbE0u2WAhVdbNBD6
sz1VgUkJItZG/k3Ahyd7+Q386AJZ3M45RtANq+KpbU3uPy5V7TY9FKEU5a1hB4IVqruqT8pIc+pc
ukDuyxH4Jp4gsMwXRDt6f1IPnOrTZdDuv3dGqijgq1b/ffv46DmqL6gfJI8AkNl8AF7GwYaT1fRO
jj98fI70PBpSsXaVAy2vngyq3gC6kjs0B1beDTKJY3YzyJbQdzFqHrZah1j9NDcUkmId80DtWrJX
pGKPRxFhPkaaqZLSJUmuEj0zQFkOSNNCPg/pioZnAfvGUz+fxpT5iQvLp5iUPyse0/pVV+8OlbMt
Us32qdhXvK3uK56n2DNK5OuWWmVQLTSME29B/SVYnMF6ISGMovX/qf4BW8E7OUAAmTwPAob6ziSL
CgQeapKQRrPAgyozEtGzIhW0jOeC+BQtKPF/R/FaLjhDWpSCVljpEQlYcy8WpVVclSqw9/X14uRQ
AwtC0y+9i9FkmPZi2EHo6X9FpzYGGH2EYtT2rULxYiCnRH99gNM0HgQ3W5H/fWCP9gF79LLAFmeL
14IU5vcgoKB/DM6t1qjGpYZUSAsGvwC4rX3gtl4WXDYP2M0j26TM5lA/Ku2UKue45sGtuur4y710
nHE2T+20ddqCEx38Nuvt7Nyw3W6nR792yfDCtDuj0WRj9BH+7rD63Q90PtOdHeruiSGdlQ7H2G/Y
oNLLxoYa677RaqlLkExbHByeelNxH21L+qQotbcWlXA79xf/6AajHHTnLuNfZdkWGKUTXrEz01RH
LWTFlQE8FweLhq7rjb8Be0O58FgUAAA='

SEP_SETTINGS_YAML='H4sIAAAAAAACA81WW2+bSBR+z68YtStZqhrjtNltw1MxTJJRMLgz0Ca7Wo0wntqsMbAMSWRV/u97
hoEAjqO9vdR+QJzvcK7fnDOvkRRVlWQrOd5F2/TkpCjz5X1cJXnGl3m8EaV5gpDluv5XbvueHVKK
vYAzzBjxPWaiqrwXrQZ2+LXPAqY+QegUvXrzSkFhcM1Dhimf+Q52TRQVxXibL0Uqx3Ykl3lehlKU
oDm17BvsOeCIMu5TckW8J1vrqiqkaRhn7z6MJ/A/Mz+en58DaFvM8X2q9dowCGMhphDe6M1IA/O5
S2wrgKC5Z82wCXkXpxBJjdqYBuRS4ZjPreDaRAZAxh+P1bgQW63iEpU4cUz003eG5xwscvV8AvZ9
PYZtioMXdDWo9SHfuU88UFUZQoKxLon5cTKZ1BqX1IdvOj3DMC/gV2M+vbI88utBXqoq2MX0Thdl
iq2AO9OQEhMVuaxWpZB/puCqfTF1lG35nSkUgbGvPnX2n5YL8+fz9+86Q8y+xjOr9QNC6t9Ab0MK
nS3FMlFN0s9f3n+4MHQOYEspsUBV2JmaKBapKHf8MS+BYlxWUaVY5FiBNbUYNpvSAAFwP+ZarChm
ouWifunnjFAbdlv3YxlpRZ+CjafEFDs7PyAi3hdolN9WcBjXi5EdxHYY3b+I71mER2JEiDGXK+pe
Ehc3lI1F2XFW4Tf4rgdvxK5Bwf0PndtTB/jwhCh6JdmDyKoc+BMViXkxmZzpw6AmTZsGxQ6h2A54
TXsjj+6rNZytNF1E8UZXxyPzOW6nFZwz4gbAUXwbYE8PtwZQ42cs15o4blhPJfTb95GqwAhGDIvX
Yhshex1lKzF6i0Yw50IX8xaP0kqUUgEQSz1flNToxDZjMBqgSD3t/VvUeSBtwkesJ31s4GCADHx0
yMCNVcbr5OFoCho5kkQPGKbR2Bo4mELt7wt5xMGiRp6ZX3QfDKy38oF1ey3ijbzfHrMf97GBiwEy
cNIhAzcsS4pCVGgWZdFKlEecSa3x3FcfGLh6AoYJ5Wkq4go5SbTK4HAkMXKiKjrWn+rxeWu0bNgV
kO1/10ym/u0dv8aWUy/KZo//v6GixgpcEUjQGW7OENwdgmb1aXzuwz6Gw31ru6Gjt+7gwIHlpGOw
AXcReYhWkdzIDmnuJJ1H/4bgZik2SzXINyJr8DoS3E/8zrN7EZ82AhPNZzO2y+L6itIMsNmsi/Vw
h6sJpUcgqKm9yNVc2n+CO86DKMerNF9E6TjLt9HS7PTUTNz3bFpzosrcTtO+KR7AxvX6yl8wJZd3
HFpjom9RKsWzHGY79tk9yIJceT7FzUJn/YROkdzJwXshym95uY3AAJf1vBvA2123J7QkyWr9+iLZ
+yCw2A07MtLrXrbjXK2FmoZWn4RRQ7LaxA+9uzx/ZjldTH9PDm7Zth96wT8iiVFLX2LxS2T478f6
L3ldUykjDAAA'

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

	cat <<-EOS | base64 -d | zcat | sed "s#\${SEP_ORG_CASDOOR_SALT}#${SEP_ORG_CASDOOR_SALT}#; s#\${SEP_ORG_SEP_SALT}#${SEP_ORG_SEP_SALT}#; s#\${SEP_APP_CASDOOR_CLIENT_ID}#${SEP_APP_CASDOOR_CLIENT_ID}#; s#\${SEP_APP_CASDOOR_CLIENT_SECRET}#${SEP_APP_CASDOOR_CLIENT_SECRET}#; s#\${SEP_APP_SEP_CLIENT_ID}#${SEP_APP_SEP_CLIENT_ID}#; s#\${SEP_APP_SEP_CLIENT_SECRET}#${SEP_APP_SEP_CLIENT_SECRET}#; s#\${SEP_USER_CASDOOR_ADMIN_PASSWD}#${SEP_USER_CASDOOR_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_ADMIN_PASSWD}#${SEP_USER_SEP_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_USER_PASSWD}#${SEP_USER_SEP_USER_PASSWD}#; s#\${SEP_IMAGE_NAME}:\${SEP_IMAGE_TAG}#${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}#g; s#\${SEP_BACKEND_DB_PASSWORD}#${SEP_BACKEND_DB_PASSWORD}#g; s#\${SEP_PMM_PORT}#${SEP_PMM_PORT}#g" >"${INSTALL_DIR}"/compose.yaml
	${SEP_COMPOSE_YAML}
	EOS

	test "${ENABLE_PMM}" = "1" || yq -i -y 'del(.services.pmm)' "${INSTALL_DIR}"/compose.yaml

	cat <<-EOS | base64 -d | zcat | sed "s#\${SEP_ORG_CASDOOR_SALT}#${SEP_ORG_CASDOOR_SALT}#; s#\${SEP_ORG_SEP_SALT}#${SEP_ORG_SEP_SALT}#; s#\${SEP_APP_CASDOOR_CLIENT_ID}#${SEP_APP_CASDOOR_CLIENT_ID}#; s#\${SEP_APP_CASDOOR_CLIENT_SECRET}#${SEP_APP_CASDOOR_CLIENT_SECRET}#; s#\${SEP_APP_SEP_CLIENT_ID}#${SEP_APP_SEP_CLIENT_ID}#; s#\${SEP_APP_SEP_CLIENT_SECRET}#${SEP_APP_SEP_CLIENT_SECRET}#; s#\${SEP_USER_CASDOOR_ADMIN_PASSWD}#${SEP_USER_CASDOOR_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_ADMIN_PASSWD}#${SEP_USER_SEP_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_USER_PASSWD}#${SEP_USER_SEP_USER_PASSWD}#; s#\${SEP_IMAGE_NAME}:\${SEP_IMAGE_TAG}#${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}#g; s#\${SEP_BACKEND_DB_PASSWORD}#${SEP_BACKEND_DB_PASSWORD}#g; s#\${SEP_PMM_URL_AUTH}#${SEP_PMM_URL_AUTH}#g; s#\${SEP_PMM_URL_AUTH_ACCOUNT}#${SEP_PMM_URL_AUTH_ACCOUNT}#g; s#\${SEP_PMM_URL_AUTH_TOKEN}#${SEP_PMM_URL_AUTH_TOKEN}#g; s#\${SEP_PMM_PORT}#${SEP_PMM_PORT}#g" >"${INSTALL_DIR}"/settings.yaml
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
