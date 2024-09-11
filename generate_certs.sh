#!/bin/bash

# Default values for additional DNS names and IPs
additional_dnsname="localhost"
additional_ip="127.0.0.1"

# Parse input arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --additional-dnsname) additional_dnsname="$2,$additional_dnsname"; shift ;;
        --additional-ip) additional_ip="$2,$additional_ip"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

data_dir="$(pwd)/data"

# Create the certs directory if it doesn't exist and enter it
mkdir -p data/certs
cd data/certs

# Generate CA key and certificate
openssl ecparam -genkey -name secp384r1 -out sep-ca-key.pem -noout
openssl req -new -x509 -key sep-ca-key.pem -nodes -out sep-ca.pem -sha384 -days 365 \
    -subj "/CN=SEP Root CA" \
    -addext "keyUsage=critical,digitalSignature,keyCertSign" \
    -addext "basicConstraints=critical,CA:true,pathlen:0" \
    -addext "subjectKeyIdentifier=hash" \
    -addext "authorityKeyIdentifier=keyid:always" \
    -addext "extendedKeyUsage=serverAuth,clientAuth"

# Generate nomad server and client certificates
nomad tls cert create -server -region global -additional-dnsname="host.docker.internal" -ca sep-ca.pem -key sep-ca-key.pem
nomad tls cert create -client -additional-dnsname="host.docker.internal" -ca sep-ca.pem -key sep-ca-key.pem

# Move global certs to the nomad directory
mkdir -p nomad
mv global*.pem nomad/

# Generate PKCS12 certificate for browsers
openssl pkcs12 -export -inkey nomad/global-client-nomad-key.pem -in nomad/global-client-nomad.pem -out nomad/global-client-nomad.p12 -passout pass:

cat > "$data_dir/nomad.hcl" <<-EOF
# Full configuration options can be found at https://www.nomadproject.io/docs/configuration

log_level = "DEBUG"

disable_update_check = true

# Setup data dir
data_dir = "/tmp/server1"

name = "pmm-server"

advertise {
  # Defaults to the first private IP address.
  http = "127.0.0.1"
  rpc  = "127.0.0.1"
  serf = "127.0.0.1" # non-default ports may be specified
}

server {
  # license_path is required for Nomad Enterprise as of Nomad v1.1.1+
  #license_path = "/etc/nomad.d/license.hclic"
  enabled          = true
  bootstrap_expect = 1
}

client {
  enabled = true
  servers = ["127.0.0.1"]
}

tls {
  http = true
  rpc  = true

  ca_file   = "$data_dir/certs/sep-ca.pem"
  cert_file = "$data_dir/certs/nomad/global-server-nomad.pem"
  key_file  = "$data_dir/certs/nomad/global-server-nomad-key.pem"

  verify_server_hostname = true
  verify_https_client    = true
}

# Enabled plugins
plugin "raw_exec" {
  config {
      enabled = true
  }
}
EOF

# Create sep directory for other certs
mkdir -p sep

# Generate localhost certificate and key
openssl ecparam -genkey -name secp384r1 -out sep/localhost-cert-key.pem -noout

# Build the subjectAltName for localhost
IFS=',' read -ra dns_arr <<< "$additional_dnsname"
IFS=',' read -ra ip_arr <<< "$additional_ip"

for dns in "${dns_arr[@]}"; do
    san="${san}DNS:$dns,"
done

for ip in "${ip_arr[@]}"; do
    san="${san}IP:$ip,"
done

san=${san::-1}

# Create a temporary openssl config for localhost cert
openssl_config=$(mktemp)
cat > "$openssl_config" <<-EOF
[ req ]
distinguished_name = req_distinguished_name
req_extensions = v3_req
[ req_distinguished_name ]
[ v3_req ]
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical,CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = $san
EOF

# Create localhost certificate
openssl req -new -key sep/localhost-cert-key.pem -out sep/localhost-cert.csr -subj "/CN=localhost"
openssl x509 -req -in sep/localhost-cert.csr -CA sep-ca.pem -CAkey sep-ca-key.pem -CAcreateserial \
    -out sep/localhost-cert.pem -days 365 -sha384 -extfile "$openssl_config" -extensions v3_req
rm sep/localhost-cert.csr

# Generate inventory_api certificate and key
openssl ecparam -genkey -name secp384r1 -out sep/inventory_api-cert-key.pem -noout

# Create a temporary openssl config for inventory_api cert
openssl_config=$(mktemp)
cat > "$openssl_config" <<-EOF
[ req ]
distinguished_name = req_distinguished_name
req_extensions = v3_req
[ req_distinguished_name ]
[ v3_req ]
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical,CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = DNS:inventory_api,DNS:localhost,IP:127.0.0.1
EOF

# Create inventory_api certificate
openssl req -new -key sep/inventory_api-cert-key.pem -out sep/inventory_api-cert.csr -subj "/CN=inventory_api"
openssl x509 -req -in sep/inventory_api-cert.csr -CA sep-ca.pem -CAkey sep-ca-key.pem -CAcreateserial \
    -out sep/inventory_api-cert.pem -days 365 -sha384 -extfile "$openssl_config" -extensions v3_req
rm sep/inventory_api-cert.csr


# Generate tasks_api certificate and key
openssl ecparam -genkey -name secp384r1 -out sep/tasks_api-cert-key.pem -noout

# Create a temporary openssl config for tasks_api cert
openssl_config=$(mktemp)
cat > "$openssl_config" <<-EOF
[ req ]
distinguished_name = req_distinguished_name
req_extensions = v3_req
[ req_distinguished_name ]
[ v3_req ]
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical,CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = DNS:tasks_api,DNS:localhost,IP:127.0.0.1
EOF

# Create tasks_api certificate
openssl req -new -key sep/tasks_api-cert-key.pem -out sep/tasks_api-cert.csr -subj "/CN=tasks_api"
openssl x509 -req -in sep/tasks_api-cert.csr -CA sep-ca.pem -CAkey sep-ca-key.pem -CAcreateserial \
    -out sep/tasks_api-cert.pem -days 365 -sha384 -extfile "$openssl_config" -extensions v3_req
rm sep/tasks_api-cert.csr