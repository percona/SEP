#!/usr/bin/env bash

# ---
# title: "MongoDB TLS Certificate Expiry Check"
# description: "This script checks MongoDB TLS certificate expiration dates to prevent service disruption from expired certificates."
# allow_extra_args: false
# sudo: optional
# service_type: mongodb
# alerts:
#   - MongoDBTLSCertificateExpiry
# ---

# Usage: ./mongodb_tls_expiry_check.sh

set -euo pipefail

MONGOSH="mongosh --quiet"
command -v mongosh &> /dev/null || MONGOSH="mongo --quiet"

echo "********* MongoDB TLS certificate expiration (from serverStatus) *********"
echo ""
$MONGOSH --eval "
var ss = db.serverStatus();
if (ss.security && ss.security.SSLServerCertificateExpirationDate) {
    var expDateRaw = ss.security.SSLServerCertificateExpirationDate;
    var expDate = (expDateRaw instanceof Date) ? expDateRaw : new Date(expDateRaw);
    if (isNaN(expDate.getTime())) {
        print('Certificate expiration date is not in a valid format: ' + expDateRaw);
    } else {
        var now = new Date();
        var daysLeft = Math.floor((expDate - now) / (1000 * 60 * 60 * 24));
        print('Certificate expires: ' + expDate);
        print('Days until expiry:   ' + daysLeft);
        if (daysLeft < 30) {
            print('WARNING: Certificate expires in less than 30 days!');
        }
    }
} else {
    print('TLS certificate info not available in serverStatus (TLS may not be enabled).');
}
" 2> /dev/null || echo "Cannot retrieve server status."

echo ""
echo "********* MongoDB TLS configuration *********"
echo ""
$MONGOSH --eval "
var params = db.adminCommand({getCmdLineOpts: 1});
if (params.parsed && params.parsed.net && params.parsed.net.tls) {
    printjson(params.parsed.net.tls);
} else if (params.parsed && params.parsed.net && params.parsed.net.ssl) {
    printjson(params.parsed.net.ssl);
} else {
    print('No TLS/SSL configuration found in command line options.');
}
" 2> /dev/null || true

echo ""
echo "********* Certificate file check (if accessible) *********"
echo ""
CERT_FILE=$($MONGOSH --eval "
var params = db.adminCommand({getCmdLineOpts: 1});
var tls = (params.parsed && params.parsed.net && params.parsed.net.tls) || {};
var ssl = (params.parsed && params.parsed.net && params.parsed.net.ssl) || {};
print(tls.certificateKeyFile || ssl.PEMKeyFile || '');
" 2> /dev/null) || true

if [ -n "${CERT_FILE:-}" ] && [ -f "$CERT_FILE" ]; then
    echo "Certificate file: $CERT_FILE"
    openssl x509 -in "$CERT_FILE" -noout -dates 2> /dev/null || echo "Cannot parse certificate."
else
    echo "Certificate file not accessible or not found."
fi
