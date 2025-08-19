#!/bin/sh
set -o errexit
set -o nounset

test "${DEBUG:-0}" = 0 || set -o xtrace

CONTAINER_ENGINE="${CONTAINER_ENGINE:-docker}"
INSTALL_DIR="${INSTALL_DIR:-.}"

# Get current user's group ID
GID="${GID:-$(id -g)}"

CERTLIST=all-in-one
PROGRESS=0

save_progress() {
	test ! -d "${INSTALL_DIR}"/sep/ || printf "%d" "${PROGRESS}" > "${INSTALL_DIR}"/sep/.progress
}

cleanup() {
	echo Done
}

trap 'save_progress' HUP INT QUIT ABRT ALRM TERM
trap 'cleanup' EXIT

generate_secrets() {
	# Create empty file with correct permissions first
	install -m 640 /dev/null "${INSTALL_DIR}"/sep/.secrets

	cat <<-EOS > "${INSTALL_DIR}"/sep/.secrets
	SEP_ORG_CASDOOR_SALT=$(openssl rand -base64 8)
	SEP_ORG_SEP_SALT=$(openssl rand -base64 8)
	SEP_APP_CASDOOR_CLIENT_ID=$(openssl rand -hex 10)
	SEP_APP_CASDOOR_CLIENT_SECRET=$(openssl rand -hex 20)
	SEP_APP_SEP_CLIENT_ID=$(openssl rand -hex 10)
	SEP_APP_SEP_CLIENT_SECRET=$(openssl rand -hex 20)
	SEP_USER_CASDOOR_ADMIN_PASSWD=$(openssl rand -base64 20)
	SEP_USER_SEP_ADMIN_PASSWD=$(openssl rand -base64 20)
	SEP_USER_SEP_USER_PASSWD=$(openssl rand -base64 20)
	EOS
}

get_engine_command() {
	case "${CONTAINER_ENGINE}" in
		docker) echo docker compose --file "${INSTALL_DIR}"/sep/compose.yaml --project-name sep;;
		podman) echo podman-compose --file "${INSTALL_DIR}"/sep/compose.yaml --project-name sep;;
		*) return 1
	esac
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

	for cmd in openssl docker docker-compose podman podman-compose; do
		case "${cmd}" in
			docker|docker-compose) test "${CONTAINER_ENGINE}" = docker || continue;;
			podman|podman-compose) test "${CONTAINER_ENGINE}" = podman || continue;;
		esac
		test -x "$(which "${cmd}")" || check_prereqs_out="${check_prereqs_out} ${cmd}"
	done

	test "${check_prereqs_out}" = "" || {
		printf "ERROR: the following commands are unavailable - %s\n" "${check_prereqs_out}";
		return 1
	}

	PROGRESS=1
}

generate_dirs() {
	install -d "${INSTALL_DIR}"/sep/certs -o "${USER}" -g "${GID}" -m 0750

	PROGRESS=2
}

generate_tls() {
	generate_secrets

	cd "${INSTALL_DIR}"/sep/certs || exit 3

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

		printf "DNS.1=localhost\nDNS.2=%s\n" sep >> openssl.conf
		printf "IP.1=%s\n" 127.0.0.1  >> openssl.conf

		openssl ecparam -genkey -name secp384r1 -out "${cert}-cert-key.pem" -noout
		openssl req -new -key "${cert}-cert-key.pem" -out "${cert}-cert.csr" -subj "/CN=${cert}"
		openssl x509 -req -in "${cert}-cert.csr" -CA sep-ca.pem -CAkey sep-ca-key.pem -CAcreateserial -out "${cert}-cert.pem" -days 365 -sha384 -extfile ./openssl.conf -extensions v3_req

		rm -f "${CERT_NAME}-cert.csr" openssl.conf
	done

	cd - || exit 3

	PROGRESS=3
}

generate_configs() {
	cat <<-EOS > "${INSTALL_DIR}"/sep/compose.yaml
	TBD
	EOS

	cat <<-EOS > "${INSTALL_DIR}"/sep/settings.yaml
	TBD
	EOS

	cat <<-EOS > "${INSTALL_DIR}"/sep/.env
	TBD
	EOS

	cat <<-EOS >  "${INSTALL_DIR}"/sep/nginx.conf
	TBD
	EOS

	cat <<-EOS >  "${INSTALL_DIR}"/sep/casdoor_init.json
	TBD
	EOS

	PROGRESS=4
}

generate_stack() {
	$(get_engine_command) up --detach --no-start

	PROGRESS=5
}

start_stack() {
	$(get_engine_command) start casdoor db redis
	sleep 5

	$(get_engine_command) start celery_worker celery_beat
	sleep 5

	$(get_engine_command) start celery_worker celery_beat
	sleep 5

	$(get_engine_command) start inventory_api tasks_api
	sleep 5

	$(get_engine_command) start app
	sleep 5

	$(get_engine_command) start nginx
}

test ! -f "${INSTALL_DIR}"/sep/.progress || PROGRESS="$(cat "${INSTALL_DIR}"/sep/.progress)"

test "${PROGRESS}" -gt 0 || check_prereqs  # Errors here will require manual intervention
test "${PROGRESS}" -gt 1 || generate_dirs
test "${PROGRESS}" -gt 2 || generate_tls
test "${PROGRESS}" -gt 3 || generate_configs
test "${PROGRESS}" -gt 4 || generate_stack

echo Setup complete

echo Do you want to start the stack now?
read -r STARTSTACK

echo "${STARTSTACK}" | grep -qi "^y$" || exit 0
start_stack
