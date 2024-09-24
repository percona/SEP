#!/bin/bash

data_dir="$(pwd)/data"

# Generate the RS256 4096-bit private key and public certificate
openssl genpkey -algorithm RSA -out "$data_dir/certs/casdoor/sep_token_jwt_key.key" -pkeyopt rsa_keygen_bits:4096
openssl rsa -pubout -in "$data_dir/certs/casdoor/sep_token_jwt_key.key" -out "$data_dir/certs/casdoor/sep_token_jwt_key.pem"

# Generate the clientId (20 chars) and clientSecret (40 chars)
clientId=$(openssl rand -hex 10)
clientSecret=$(openssl rand -hex 20)

# Generate the user password (20 chars) if not provided as a parameter
password=""
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    -p|--password) password="$2"; shift ;;
  esac
  shift
done

if [[ -z "$password" ]]; then
  password=$(openssl rand -hex 15)
fi
adminPassword=$(openssl rand -hex 20)

# Read the generated certificate and private key, replacing line breaks with "\n"
certificate=$(awk '{printf "%s\\n", $0}' "$data_dir/certs/casdoor/sep_token_jwt_key.pem")
privateKey=$(awk '{printf "%s\\n", $0}' "$data_dir/certs/casdoor/sep_token_jwt_key.key")

# Create the casdoor_init_data.json file with replaced values
cat > "$data_dir/casdoor_init_data.json" <<EOL
{
  "organizations": [
    {
      "owner": "admin",
      "name": "sep",
      "displayName": "Services Enablement Platform",
      "websiteUrl": "https://github.com/percona/SEP",
      "favicon": "https://docs.percona.com/percona-platform/images/percona-logo.svg",
      "passwordType": "plain",
      "passwordSalt": "",
      "passwordOptions": [
        "AtLeast6"
      ],
      "countryCodes": [
        "US",
        "GB",
        "ES",
        "FR",
        "DE",
        "CN",
        "JP",
        "KR",
        "VN",
        "ID",
        "SG",
        "IN",
        "IT",
        "MY",
        "TR",
        "DZ",
        "IL",
        "PH",
        "NL",
        "PL",
        "FI",
        "SE",
        "UA",
        "KZ",
        "CZ",
        "SK"
      ],
      "defaultAvatar": "",
      "defaultApplication": "",
      "tags": [],
      "languages": [
        "en",
        "zh",
        "es",
        "fr",
        "de",
        "id",
        "ja",
        "ko",
        "ru",
        "vi",
        "it",
        "ms",
        "tr",
        "ar",
        "he",
        "nl",
        "pl",
        "fi",
        "sv",
        "uk",
        "kk",
        "fa",
        "cs",
        "sk"
      ],
      "masterPassword": "",
      "defaultPassword": "",
      "initScore": 2000,
      "enableSoftDeletion": false,
      "isProfilePublic": true,
      "accountItems": []
    }
  ],
  "applications": [
    {
      "owner": "admin",
      "name": "sep-app",
      "displayName": "SEP App",
      "logo": "https://docs.percona.com/percona-platform/images/percona-logo.svg",
      "homepageUrl": "https://github.com/percona/SEP",
      "organization": "sep",
      "cert": "sep-cert",
      "enablePassword": true,
      "enableSignUp": true,
      "clientId": "$clientId",
      "clientSecret": "$clientSecret",
      "signinMethods": [
        {
          "name": "Password",
          "displayName": "Password",
          "rule": "All"
        },
        {
          "name": "Verification code",
          "displayName": "Verification code",
          "rule": "All"
        }
      ],
      "signupItems": [],
      "grantTypes": [
        "authorization_code",
        "password"
      ],
      "redirectUris": [
        "https://localhost/oauth/callback",
        "https://127.0.0.1/oauth/callback"
      ],
      "tokenFormat": "JWT",
      "tokenFields": [],
      "expireInHours": 168,
      "failedSigninLimit": 5,
      "failedSigninFrozenTime": 15
    }
  ],
  "users": [
    {
      "owner": "sep",
      "name": "admin",
      "type": "normal-user",
      "password": "$adminPassword",
      "displayName": "",
      "avatar": "",
      "email": "",
      "phone": "",
      "countryCode": "",
      "address": [],
      "affiliation": "",
      "tag": "",
      "score": 2000,
      "ranking": 1,
      "isAdmin": true,
      "isForbidden": false,
      "isDeleted": false,
      "signupApplication": "sep-app",
      "createdIp": ""
    },
    {
      "owner": "sep",
      "name": "sep",
      "type": "normal-user",
      "password": "$password",
      "displayName": "",
      "avatar": "",
      "email": "",
      "phone": "",
      "countryCode": "",
      "address": [],
      "affiliation": "",
      "tag": "",
      "score": 2000,
      "ranking": 1,
      "isAdmin": false,
      "isForbidden": false,
      "isDeleted": false,
      "signupApplication": "sep-app",
      "createdIp": ""
    }
  ],
  "certs": [
    {
      "owner": "admin",
      "name": "sep-cert",
      "displayName": "SEP Certificate",
      "scope": "JWT",
      "type": "x509",
      "cryptoAlgorithm": "RS256",
      "bitSize": 4096,
      "expireInYears": 20,
      "certificate": "$certificate",
      "privateKey": "$privateKey"
    }
  ]
}
EOL

echo "$data_dir/casdoor_init_data.json created successfully."

cat > ".env.docker" <<EOL
CASDOOR__CLIENT_ID=$clientId
CASDOOR__CLIENT_SECRET=$clientSecret
PMM__API_KEY=REPLACE_WITH_YOUR_PMM_API_KEY
EOL

echo ".env.docker created successfully."
echo "User sep created with password: $password"
echo "User admin created with password: $adminPassword"

# TODO: Call this script from the Dockerfile