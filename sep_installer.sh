#!/bin/sh

set -o errexit
set -o nounset

test "${DEBUG:-0}" = 0 || set -o xtrace

CONTAINER_ENGINE="${CONTAINER_ENGINE:-docker}"
INSTALL_DIR="${INSTALL_DIR:-"${HOME}/sep"}"

CERTLIST=all-in-one
PROGRESS=0


# shellcheck disable=SC2016
CASDOOR_INIT_JSON_DATA='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
ib/8DR+8zpieGwAA'

NGINX_CONFIG='H4sICDtG2mgCA25naW54LmNvbmYA7VOxbtswEN39FTcIyORKQQ3UdsYCRboFAQJ0IxjyZBOheMwd
ldgt8u+lItlqHdvIlg7lRN57j0c+PjY6QrFOKao2rlhbhMJQCGiSo7Cv/ZpAHhZr3foEQ/XqtXhx
AcaT5NXLZCLIT8gD3TtJGGBezaue2qMq6AbBk9F+TZL+ghI9YBCguu7LjKnlAJ+rS+jOKMuyLDpR
wfjYoiTVsjvdeDabgYh/21ydbNrXxSuDnFztjE4IJSZThpULm1IwTjvoU8Tm6hhZPeD2UJBLPf9V
YLzDkFSjN+qe7FaJ+4lwuUM7XzrroRwu043ItNmqqEX2NugYl4uqGpwdSYJJrTG/DsN1Nmp429Ho
o8wf01vUfvr9BrKxDeVbaGv5rOAb8bNmi7abQdEzskptVL2Dutk7N7lhSgSFmDU2eEZztwvpn5E9
w/+6z/KxXB8KGa3jTBkDOGL3bV0ju7AawZdTyVvk8Q8mD5mJc4xWCLPFl7e/alkM54rEB1/s3dnM
exktloiX8//x/PB4/gbqdx6+3wUAAA=='

SEP_COMPOSE_YAML='H4sICM5x2mgCA2NvbXBvc2UueWFtbADdWEtv2zgQvvtXEN6ih6J6JHHTltselFh1jPULlt3dngRa
Ym01EqmlaCdukf++QypWJFlO0kXTYjcBBM1Tw/lmxiQNw2j9hjZRghHjJMKMU9lqXRskjQzKNpHg
LKFM4hZCZRI9rymAHKEPjjdzJn3fHX3EKBU8XAcy4swPeXBJhVYBkf+hP3AxskK6sdg6jjXfc2ez
/qjn7YQySa2MShmxZWZuSRLvggoXD8dV1dH+373D6EVTzF1n5pw5nutD1L3+CL6d8kwuBc3+1t8M
WWbQaymIsQJ+pj+oSD8n0fOagnZqoHZGxYYKcxnzBYlNxhMS4mffLsbezO9PsNY1lkTSK7K9ae+M
FNfMs2VGTFLBSHyPFYSX0dTY8HidUB3a7hU9V4KMBoIWIT371h8BPoOB3+1PsWHeWAEVMoM0p77k
l5T5X66kf0m3ZkoTbJE0tYChCcFffn3YixGQO9Pb90dYkjg2ImZwRg3FKLnYUd/vxKgsY0fc66dS
bXi/AHPrFqPyiotLne00SbD2RxlZxNSP0s0pRp9JnNEau4ORFGvaAjYE9J1GikukJMFKSXa6LVVh
UUCrkUQJWYLKroa4lVIRcEYs0DDymsQnWrNUNXlKlEZIJMFWJjaam3IhSwpvOp0TrB63cVa6UP1N
hkO/657NexjZJZY7cs4Gru8M3KnqcYyO9oVnzvkf84k/dEZOzx26o1mji9F46HQb7WfuAMxm00+N
dvMJtLnrVWWT+dmgf+473e7U9UB2qM/uloxQ74PvuefzaX/2CQyH/ZE/cTzvz/G0q+zvkRokTCJ2
k2euPD9eNM0PmD6SCBhnJIYIcl658ArAVEEFJAs5FwfwB+kiYtatknHXJ81FsNPLC2FDhBVHCyvZ
wjTEX1+Kq0KxoRFzUz9ikTS/ZJxhS736ylVOF/1Hr2HI0lJl2bb9yNTspwEaqjFpwAwXB7ICixJE
bK3drMdHpweLGoqiBxXid88wgilXZ889d3r3o1GXlsvDcye6zt1RF5wVopu6jS5DZz678KGiL8Zg
mwWCQPuuiHH86rQZODV/q6Dd/Y5ZWlDAV8/+q87J8VNkX9Awyh4AINd5DXWZRrc1WQ/v9OT126cI
L6AxFVtfGdBq9+RQ9YcwivyRM3RvcJkzc3o5ZGuYpxi1j2z7CKtH+7aEpNimPFK7kfwTmh3wJCEs
xMhwVFCmJNllZuYKKI8BGUbMlzHd0Ph9xD5zbRfSlLIw86F9ikWFi+JV56/evXulnG99GrZFxX7h
RX2/8DTJXlAif22qVQT1RAOdBSsarkHjPfQLiYFKtv+n/EdsA9/kAAFE8jQIWOp3JlvVIAhQm8Q0
WUQBZJmRhL4vQkHrdClISNGKkvB3lG7lijNkJBq0QstMSMTaB7GodHGdq8A+NNeLE0EDLAjNP/bP
x9ORnsWw4Th+bdrwf1STTsZTkL6FdDROrkLw02DWpf7rIdZh3Atv3pP/BWiPD0F7/HOhLc4NvwpU
WN+9kIL8IUBL41HRlaFUcIsa/hHw2hpc+xC49iFw7Z8LLltG7PqBrVKuc2QeV3ZLtTNa+9k3dY3x
l38xm03ydRpv7Dc2nGLg2W7W83aKnU5HH3c6FcVzx+uOx9Nbpbfwd4PV8zDQu5Xu7VL3Tw16VSYc
UT9ji8ogpy1Fm6Fl2+qCI5cWh4fH3kLceStxH+Wl8Uai5m7vbuJf3U5Une7dU/zQKiuBUTnlFbsz
Q83UgldcB8B7cbhomabZ+gclSeNxNBQAAA=='
SEP_SETTINGS_YAML='H4sICONy2mgCA3NldHRpbmdzLnlhbWwAzVZbb9s2FH7PryDaAQaKxnKabG30VFliEsKy6JJSG28Y
CFlmY88XaaKcwij833coSpHkOAO2vtR+sMXv8Jzv3PUaKVkUy+2D6u/jzfrsLMvT+S4plulWzNNk
JXP7DCHH9+kX4dLAjRjDQSg45pzQgNuoyHeylsCeuKM85PoKQufo1ZtXGorCOxFxzMSYeti3UZxl
/U06l2vVd2M1T9M8UjIHyaHjjnDggSHGBWXklgRPuhZFkSnbsi7eve8P4Hthf7i6ugLQdbhHKTNy
NQ3CeYQZ0Ou96RlgMvGJ64RAWgTOGNvgd3YOTErUxSwkNxrHYuKEdzayALL++lb0M7kxIj7RjhPP
Rr9853giQKOobIsn8NCW5dhlOPwXeSNg7oDfE0oCENeegqOJCY39YTAYlBI3jMKdRs6y7Gv4lBhl
t05Afj/yT0cH+5hNTXCG2AmFN4wYsVGWquIhl+rvNZiqH2zDtE6DN4RgcP6FMu/wcT6zf726fNco
4u4dHju1HThkdAQ5jhhkOJfzpU6W+f3t8v21ZXwAXVqIhzrS3tBGiVzLfC++pTmUmlBFXOhq8pzQ
GToc21VooBBwm3N5rEvNRvNZ+dD2GaGadh37Ux4ZQcpAx5NjukobO3BEgs+QKFpHsMvrRWZH3I7Z
/Qd+zxie4IgQ577QJXxDfFyVbiLzpnY1PsLTFryS+woF8z+1b08ZEN0O0eW13D7KbZFC/cTZ0r4e
DC5MM+iJU7vBsEcYdkNRlr2VxrtiAb21Xs/iZGWiE5DJBNdTC/qM+CHUKL4PcWCGXAXoMdRXC1M4
flROJ/TH956OQA9GDU8WchMjdxFvH2TvLerBvIt8LGo8XhcyVxoALuWc0adWc+xyDqMBgtSSPrxF
jQVSO3xC+7KNdQx0kI6NBumYcfJksXw86YJBTjjRArpuVLo6BoYQ+12mThiYlcgz9bPmQkd7fd7R
7i5kslK7zSn9SRvrmOggHSMNcvjTJJ/R+6m4w45X7phqBf5YH+pOhO1KwkZxVXawdsNqWxh8QmGV
QT/cu37kmYXVqVHQvGySbsEaV8doEauVapBqnTcW6Yjgao9UeyhMV3Jb4SUT3HZ8GrgtxufVgY0m
4zHfb5Nyu1c9Px43XI/Xnm5qMzVATK8SoVv58BFeDx5l3n9Yp7N43d+mm3iu1/9lS9FnzMjNVECI
bfQ1Xiv5jMt4zz/5R2zIbUAZrnYZbxM7R2qvOs+ZzL+m+SYGBUKVrd6BN/tmRJqT5baUL9+lWhdC
h4/4iWlW5qSeZHoiluXktIsproqlVPFTj+2Ajh2v4fQjSbbKvy+V3kuZ//+9+A92vGjiEwsAAA=='

SEP_IMAGE_NAME="${SEP_IMAGE_NAME:-docker.io/percona/percona-sep}"
SEP_IMAGE_TAG="${SEP_IMAGE_TAG:-v0.9.0}"


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
		docker) echo "${CONTAINER_ENGINE}" compose --file "${INSTALL_DIR}"/compose.yaml --project-name sep;;
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

	for cmd in openssl docker podman podman-compose; do
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

	cat <<-EOS | base64 -d | zcat | sed "s#\${SEP_ORG_CASDOOR_SALT}#${SEP_ORG_CASDOOR_SALT}#; s#\${SEP_ORG_SEP_SALT}#${SEP_ORG_SEP_SALT}#; s#\${SEP_APP_CASDOOR_CLIENT_ID}#${SEP_APP_CASDOOR_CLIENT_ID}#; s#\${SEP_APP_CASDOOR_CLIENT_SECRET}#${SEP_APP_CASDOOR_CLIENT_SECRET}#; s#\${SEP_APP_SEP_CLIENT_ID}#${SEP_APP_SEP_CLIENT_ID}#; s#\${SEP_APP_SEP_CLIENT_SECRET}#${SEP_APP_SEP_CLIENT_SECRET}#; s#\${SEP_USER_CASDOOR_ADMIN_PASSWD}#${SEP_USER_CASDOOR_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_ADMIN_PASSWD}#${SEP_USER_SEP_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_USER_PASSWD}#${SEP_USER_SEP_USER_PASSWD}#; s#\${SEP_IMAGE_NAME}:\${SEP_IMAGE_TAG}#${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}#g; s#\${SEP_BACKEND_DB_PASSWORD}#${SEP_BACKEND_DB_PASSWORD}#g" >"${INSTALL_DIR}"/settings.yaml
	${SEP_SETTINGS_YAML}
	EOS

	cat <<-EOS | base64 -d | zcat >"${INSTALL_DIR}"/nginx.conf
	${NGINX_CONFIG}
	EOS

	cat <<-EOS | base64 -d | zcat | sed "s#\${SEP_ORG_CASDOOR_SALT}#${SEP_ORG_CASDOOR_SALT}#; s#\${SEP_ORG_SEP_SALT}#${SEP_ORG_SEP_SALT}#; s#\${SEP_APP_CASDOOR_CLIENT_ID}#${SEP_APP_CASDOOR_CLIENT_ID}#; s#\${SEP_APP_CASDOOR_CLIENT_SECRET}#${SEP_APP_CASDOOR_CLIENT_SECRET}#; s#\${SEP_APP_SEP_CLIENT_ID}#${SEP_APP_SEP_CLIENT_ID}#; s#\${SEP_APP_SEP_CLIENT_SECRET}#${SEP_APP_SEP_CLIENT_SECRET}#; s#\${SEP_USER_CASDOOR_ADMIN_PASSWD}#${SEP_USER_CASDOOR_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_ADMIN_PASSWD}#${SEP_USER_SEP_ADMIN_PASSWD}#; s#\${SEP_USER_SEP_USER_PASSWD}#${SEP_USER_SEP_USER_PASSWD}#; s#\${SEP_IMAGE_NAME}:\${SEP_IMAGE_TAG}#${SEP_IMAGE_NAME}:${SEP_IMAGE_TAG}#g; s#\${SEP_BACKEND_DB_PASSWORD}#${SEP_BACKEND_DB_PASSWORD}#g" >"${INSTALL_DIR}"/casdoor_init.json
	${CASDOOR_INIT_JSON_DATA}
	EOS

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

echo Do you want to start the stack now?
read -r STARTSTACK

echo "${STARTSTACK}" | grep -qi "^y$" || exit 0
start_stack
