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
while [[ $# -gt 0 ]]; do
    case "$1" in
        -p | --password)
            password="$2"
            shift
            ;;
    esac
    shift
done

if [[ -z $password ]]; then
    password=$(openssl rand -hex 15)
fi
adminPassword=$(openssl rand -hex 20)
perconaLogo="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYwIiBoZWlnaHQ9IjE2MCIgdmlld0JveD0iMCAwIDE2MCAxNjAiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxyZWN0IHdpZHRoPSIxNjAiIGhlaWdodD0iMTYwIiByeD0iMjQiIGZpbGw9IiMwRTFBNTMiLz4KPHBhdGggZD0iTTExMi43MjYgODYuNjM5NEMxMjMuODIxIDc5LjM5MjEgMTI3LjQ1MSA2NC42MDkgMTIwLjczNyA1Mi45OTAzQzExNy4zNzMgNDcuMTYyNCAxMTEuOTM1IDQyLjk4ODcgMTA1LjQyOSA0MS4yNDU5Qzk5LjQwMTYgMzkuNjI4NyA5My4xMDYyIDQwLjI5IDg3LjU2NTIgNDMuMDg3Nkw4MCAzMEw2NC4yOTY1IDU3LjE4MDVMMjggMTIwSDEzMkwxMTIuNzI2IDg2LjYzOTRaTTEwMy42NSA0Ny45MDRDMTA4LjM3OSA0OS4xNjI3IDExMi4zMTQgNTIuMTk3MiAxMTQuNzY1IDU2LjQyMjRDMTE5LjU4MiA2NC43NTEyIDExNy4wOCA3NS4zMTUyIDEwOS4yNjcgODAuNjUwN0w5MS4wMjAxIDQ5LjA3Qzk0Ljk1MTEgNDcuMTgwOSA5OS4zODUxIDQ2Ljc2ODkgMTAzLjY1IDQ3LjkwNFpNODAgNDMuNzk0MkwxMjAuMDQgMTEzLjEwMUg5Ni42MTI1TDY4LjI4MTEgNjQuMDc3Nkw3OS45OTc5IDQzLjc5NjJMODAgNDMuNzk0MlpNMzkuOTYgMTEzLjEwMUw2NC4yOTQ1IDcwLjk4OTFMODguNjI4OSAxMTMuMTAxSDM5Ljk2WiIgZmlsbD0idXJsKCNwYWludDBfbGluZWFyXzEyOTA0XzgyMTg2KSIvPgo8ZGVmcz4KPGxpbmVhckdyYWRpZW50IGlkPSJwYWludDBfbGluZWFyXzEyOTA0XzgyMTg2IiB4MT0iNDAuNDkwMSIgeTE9IjExMi43NDIiIHgyPSIxMjEuNTE4IiB5Mj0iNjguMjc5NCIgZ3JhZGllbnRVbml0cz0idXNlclNwYWNlT25Vc2UiPgo8c3RvcCBzdG9wLWNvbG9yPSIjRkMzNTE5Ii8+CjxzdG9wIG9mZnNldD0iMSIgc3RvcC1jb2xvcj0iI0YwRDEzNiIvPgo8L2xpbmVhckdyYWRpZW50Pgo8L2RlZnM+Cjwvc3ZnPgo="

# Read the generated certificate and private key, replacing line breaks with "\n"
certificate=$(awk '{printf "%s\\n", $0}' "$data_dir/certs/casdoor/sep_token_jwt_key.pem")
privateKey=$(awk '{printf "%s\\n", $0}' "$data_dir/certs/casdoor/sep_token_jwt_key.key")

# Create the casdoor_init_data.json file with replaced values
cat > "$data_dir/casdoor_init_data.json" << EOL
{
  "organizations": [
    {
      "owner": "admin",
      "name": "sep",
      "displayName": "Services Enablement Platform",
      "websiteUrl": "https://github.com/percona/SEP",
      "favicon": "$perconaLogo",
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
      "logo": "$perconaLogo",
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
      "tokenFormat": "JWT-Custom",
      "tokenFields": ["Owner", "Name", "Id"],
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

cat > ".env.docker" << EOL
AUTH__PROVIDER__CASDOOR__CLIENT_ID=$clientId
AUTH__PROVIDER__CASDOOR__CLIENT_SECRET=$clientSecret
PMM__API_KEY=REPLACE_WITH_YOUR_PMM_API_KEY
EOL

echo ".env.docker created successfully."
echo "User sep created with password: $password"
echo "User admin created with password: $adminPassword"

# TODO: Call this script from the Dockerfile
