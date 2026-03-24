# SEP - Services Enablement Platform

## Table of Contents

* [Prerequisites](#prerequisites)
* [Setup](#setup)
* [Configuration](#configuration)
   * [Plugins](#plugins)
   * [Secrets](#secrets)
      * [Getting Casdoor's Client ID and Client Secret](#getting-casdoors-client-id-and-client-secret)
   * [Environment](#environment)
   * [Syncers](#syncers)
      * [PMMSyncer](#pmmsyncer)
         * [Getting your PMM API Key](#getting-your-pmm-api-key)
      * [MySQLSyncer](#mysqlsyncer)
* [Usage](#usage)
  * [Starting Celery with SEP for development](#starting-celery-with-sep-for-development)
* [Alternative: Use Docker Compose](#alternative-use-docker-compose)
* [Contributing](#contributing)
* [Deployment](#deployment)

## Prerequisites

- **Python Version Requirements**
```text
  >=3.11.9, !=3.12.0, !=3.12.1, !=3.12.2, <3.14
```

- [Casdoor](https://casdoor.org/docs/basic/server-installation) or [Docker](https://docs.docker.com/get-started/get-docker/)

You can start Casdoor on port 9999 with Docker by running
```shell
docker run --detach --name casdoor \
--volume casdoor-data:/var/lib/mysql:z,rw \
--publish 9999:8000/tcp \
casbin/casdoor-all-in-one
```

- [PMM](https://docs.percona.com/percona-monitoring-and-management/setting-up/server/index.html) or [Docker](https://docs.docker.com/get-started/get-docker/)

You can start PMM with Docker by running
```shell
docker run --detach --restart always \
--publish 8443:443 \
--volume pmm-data:/srv \
--name pmm-server \
percona/pmm-server:2
```

- [Percona Toolkit](https://www.percona.com/percona-toolkit)
- [Nomad](https://developer.hashicorp.com/nomad/tutorials/get-started/gs-install)

For the purpose of development, you can run Nomad with
```shell
sudo nomad agent -node="pmm-server" -dev \
        -bind 0.0.0.0 \
        -network-interface='{{ GetDefaultInterfaces | attr "name" }}'
```

- [Celery](https://docs.celeryq.dev/en/stable/)

You can start the Celery Worker with:
```shell
celery -A app.tasks.celery worker -l info
```

and the Celery Beart with:
```shell
celery -A app.tasks.celery beat -S sqlalchemy --loglevel=info
```

For development purposes, you can also [start Celery with SEP](#starting-celery-with-sep-for-development).

## Setup

1. Clone the repository and enter the cloned folder:
```shell
git clone https://github.com/percona/SEP.git
cd SEP
```

2. Create and activate a virtualenv with the required packages:
```shell
make venv
source venv/bin/activate
```

> [!TIP]
> Use `venv/bin/activate.fish` if you're on a Fish shell.

3. Create SEP's databases with `make migrate`:
```shell
make migrate
```

4. Add your Redirect URL to the Casdoor application

In Casdoor's web interface, navigate to Identity > Applications > app-built-in
(should be in [this link](http://localhost:9999/applications/built-in/app-built-in))
and scroll to **Redirect URLs**.

The Redirect URL you should add depends on how SEP is running (see [Usage](#usage)).
For example, if you're running SEP in your localhost with HTTP in port 8000, you shoul
add the URLs `http://localhost:8000/oauth/callback` and `http://127.0.0.1:8000/oauth/callback`.

![image](https://github.com/user-attachments/assets/8a562b77-00c7-4192-bba3-d22e3514766f)

6. Create a .env file in the project root folder to store your secrets.
See the [secrets section](#secrets) of the README for more details.

## Configuration

SEP will read settings in the following order of priority:
1. Environment variables
2. .env file
3. Settings file

By default, the .env file is expected to be `.env` and the settings file `settings.yaml`.
You can change that by using the environment variables `ENV_FILE` and `SETTINGS_FILE`.

The [settings.yaml](https://github.com/percona/SEP/blob/main/settings.yaml) has base settings that you can (but don't need to) change.

Some settings are app-specific and you might not need them for running another app.
These are some, but not all, the possible settings you can have, per app:


| Name                       | App       | Required | Default                                             | settings.yaml (development)                      |
|----------------------------|-----------|----------|-----------------------------------------------------|--------------------------------------------------|
| BASE_URL                   | all       | no       | Built from the user's request                       | N/A                                              |
| ALLOWED_HOSTS              | all       | yes      | N/A                                                 | `["localhost", "127.0.0.1"]`                     |
| ALLOW_CONCURRENT_SESSIONS  | all       | no       | False                                               | False                                            |
| SSL_CAFILE                 | all       | no       | null                                                | null                                             |
| CASDOOR__ENDPOINT          | all       | yes      | N/A                                                 | `http://localhost:9999`                          |
| CASDOOR__FRONT_ENDPOINT    | all       | no       | The same as `CASDOOR__ENDPOINT`                     | `//:9999`                                        |
| CASDOOR__CERTIFICATE_PATH  | all       | no       | null                                                | null                                             |
| CASDOOR__ORGANIZATION_NAME | all       | no       | built-in                                            | N/A                                              |
| CASDOOR__APPLICATION_NAME  | all       | no       | app-built-in                                        | sep-app                                          |
| CASDOOR__ALLOWED_ISSUERS   | all       | no       | `[CASDOOR__ENDPOINT]`                               | `[http://localhost:9999, http://127.0.0.1:9999]` |
| CELERY__BROKER_URL         | all       | no       | N/A                                                 | filesystem://                                    |
| CELERY__BEAT_DBURI         | all       | no       | N/A                                                 | sqlite:///schedule.db                            |
| AUTH_USER_MODEL            | all       | no       | app.core.auth.models.BaseUser                       | app.models.CasdoorUser                           |
| LOGGING                    | all       | no       | WARNING                                             | N/A                                              |
| BACKEND_CORS_ORIGINS       | all       | no       | []                                                  | [http://localhost:8000, http://127.0.0.1:8000]   |
| TASKS__NOMAD__ENDPOINT     | tasks     | yes      | N/A                                                 | http://127.0.0.1:4646                            |
| TASKS__NOMAD__SECURE       | tasks     | no       | False                                               | N/A                                              |
| TASKS__NOMAD__VERIFY_SSL   | tasks     | no       | False                                               | True                                             |
| TASKS__NOMAD__TIMEOUT      | tasks     | no       | 10                                                  | 10                                               |
| TASKS__NOMAD__MINIFY_PAYLOAD | tasks   | no       | True                                                | True                                             |
| TASKS__NOMAD__LOG_SOCKET_READ_TIMEOUT | tasks | no | 10                                        | 10                                               |
| TASKS__SYNC_LOCK_TTL       | tasks     | no       | 300                                                 | 300                                              |
| TASKS__ANONYMIZER__DEFAULT_ENTITIES | tasks | no | "*"                                         | "*"                                              |
| TASKS__EXECUTE_MODE        | tasks     | no       | background                                          | N/A                                              |
| TASKS__DATABASE__ENGINE    | tasks     | no       | sqlite                                              | N/A                                              |
| TASKS__DATABASE__NAME      | tasks     | no       | tasks.db                                            | N/A                                              |
| TASKS__DATABASE__USER      | tasks     | no       | N/A                                                 | N/A                                              |
| TASKS__DATABASE__PASSWORD  | tasks     | no       | N/A                                                 | N/A                                              |
| TASKS__DATABASE__HOST      | tasks     | no       | ""                                                  | ""                                               |
| TASKS__DATABASE__PORT      | tasks     | no       | N/A                                                 | N/A                                              |
| SEP__INVENTORY_ENDPOINT    | sep       | yes      | N/A                                                 | http://localhost:8000/api/inventory              |
| SEP__TASKS_ENDPOINT        | sep       | yes      | N/A                                                 | http://localhost:8000/api/tasks                  |
| SEP__OAUTH__REDIRECT_URI   | sep       | yes      | N/A                                                 | /oauth/callback                                  |
| SEP__OAUTH__POST_LOGIN_URI | sep       | no       | /                                                   | N/A                                              |
| SEP__OAUTH__AUTH_LINK      | sep       | no       | CasdoorOptions.SYNC_SDK.get_auth_link(REDIRECT_URI) | N/A                                              |
| SEP__PROXY_HEADERS         | sep       | no       | False                                               | False                                            |
| SEP__SYNC_REFRESH_TIME     | sep       | no       | 5                                                   | 5                                                |
| SEP__SESSION__COOKIE_NAME  | sep       | no       | authToken                                           | casdoorToken                                     |
| SEP__SESSION__SECURE       | sep       | no       | False                                               | False                                            |
| SEP__SESSION__HTTP_ONLY    | sep       | no       | True                                                | True                                             |
| SEP__SESSION__SAME_SITE    | sep       | no       | lax                                                 | lax                                              |
| SEP__SESSION__MAX_AGE      | sep       | no       | 3600                                                | 3600                                             |
| SEP__TEMPLATES_DIR         | sep       | no       | templates                                           | templates                                        |
| SEP__STATIC_DIR            | sep       | no       | static                                              | N/A                                              |
| SEP__SECURITY_HEADERS__CONTENT_SECURITY_POLICY_EXCLUDE_PATHS | sep | no | [] | [/api/inventory/docs, /api/tasks/docs] |
| ALERTING__SOURCE_SUFFIX    | all       | no       | ""                                                  | ":dev"                                           |


Path settings (`CASDOOR__CERTIFICATE_PATH`, `TEMPLATES_DIR`, `STATIC_DIR`, etc.) may have
relative or absolute values. Relative paths will be resolved from the project root folder.

### Session Management

SEP provides configurable session management through the `SEP__SESSION` section:

```yaml
SEP:
  SESSION:
    COOKIE_NAME: casdoorToken
    SECURE: False
    HTTP_ONLY: True
    SAME_SITE: lax
    MAX_AGE: 3600
```

- `COOKIE_NAME`: Name of the session cookie
- `SECURE`: Whether the cookie should only be sent over HTTPS
- `HTTP_ONLY`: Whether the cookie should be accessible only via HTTP(S)
- `SAME_SITE`: SameSite attribute for the cookie (lax, strict, none)
- `MAX_AGE`: Maximum age of the session in seconds

### CSRF Protection

SEP uses double-submit cookie CSRF protection. The same token can be reused for
multiple POST requests (e.g. from a React SPA), so you do not need to refetch
a token after each request. Send the token in the `X-CSRF-TOKEN` header or in
the form body as `csrf-token`. The token expires with the session (see
[Session Management](#session-management)).

CSRF token lifetime is tied to the session `MAX_AGE`. Use the same
`SEP__SESSION` section to control how long the token stays valid:

```yaml
SEP:
  SESSION:
    COOKIE_NAME: casdoorToken
    MAX_AGE: 604800   # 7 days (seconds); CSRF token expires after the same period
```

### Security Headers

SEP supports configurable security headers through the `SEP__SECURITY_HEADERS` section:

```yaml
SEP:
  SECURITY_HEADERS:
    CONTENT_SECURITY_POLICY_EXCLUDE_PATHS:
      - /api/inventory/docs
      - /api/tasks/docs
```

This allows you to exclude specific paths from Content Security Policy restrictions.

### Anonymizer Configuration

The anonymizer plugin can be configured through the `TASKS__ANONYMIZER` section:

```yaml
TASKS:
  ANONYMIZER:
    DEFAULT_ENTITIES: "*"  # Default PII entities to anonymize
```

The `DEFAULT_ENTITIES` setting specifies which Personally Identifiable Information (PII) entities should be anonymized by default.

### Sync Configuration

SEP provides several sync-related configuration options:

- `SEP__SYNC_REFRESH_TIME`: Browser refresh interval during sync operations (in seconds)
- `TASKS__SYNC_LOCK_TTL`: TaskHistory sync lock timeout (in seconds)

### Nomad Advanced Configuration

Additional Nomad configuration options are available:

- `TASKS__NOMAD__MINIFY_PAYLOAD`: Whether to minify payloads before dispatch
- `TASKS__NOMAD__LOG_SOCKET_READ_TIMEOUT`: Socket read timeout for logs (in seconds)

> [!CAUTION]
> *Do not store secrets in settings.yaml, as the file is shared in the git repository.
> See the [secrets section](#secrets) of the README for more details.

### Plugins

SEP works with modular plugins. Plugins are FastAPI routers that will be added to the application
according to defined settings. Each plugin must have their own module in `app.sep.plugins`
with a `router` inside. The following plugins are configured by default:

```yaml
PLUGINS:
  - NAME: Schema Change
    MODULE_NAME: alters
    URI_PATH: /alters
    CSS_CLASS: alters
  - NAME: Inventory
    MODULE_NAME: inventory
    URI_PATH: /inventory
    CSS_CLASS: inventory
  - NAME: Archive
    MODULE_NAME: archives
    URI_PATH: /archives
    CSS_CLASS: archive
  - NAME: MySQL Backups
    MODULE_NAME: backup
    URI_PATH: /backups
    CSS_CLASS: backups
  - NAME: Checksums
    MODULE_NAME: checksums
    URI_PATH: /checksums
    CSS_CLASS: checksums
  - NAME: MongoDB Backups
    MODULE_NAME: backup_mongo
    URI_PATH: /backup_mongo
    CSS_CLASS: backup_mongo
```

Each plugin configuration includes:
- `NAME`: Display name for the plugin
- `MODULE_NAME`: Python module name in `app.sep.plugins`
- `URI_PATH`: URL path where the plugin will be accessible
- `CSS_CLASS`: CSS class for styling the plugin in the UI

### Secrets

SEP needs some keys and secrets to interact with Casdoor. They are:
- `CASDOOR__CLIENT_ID`
- `CASDOOR__CLIENT_SECRET`

You can create a basic .env file template by running the following command in the project root folder:
```shell
echo -e "CASDOOR__CLIENT_ID=YOUR_CASDOOR_CLIENT_ID\nCASDOOR__CLIENT_SECRET=YOUR_CASDOOR_CLIENT_SECRET\n" > .env
```

#### Getting Casdoor's Client ID and Client Secret

1. In a browser, open Casdoor's web interface and login (the default credentials are `admin:123`).
If you followed the Docker tutorial, it should be in http://localhost:9999.

![image](https://github.com/user-attachments/assets/770d9957-ca7e-48b5-8e40-1dd232038fde)

2. Navigate to Identity > Applications > app-built-in. If you followed the Docker tutorial,
it should be in http://localhost:9999/applications/built-in/app-built-in

![image](https://github.com/user-attachments/assets/2b95de9d-33ce-4f60-9457-f89e7c6ce619)

3. Copy the app's Client ID and Client Secret and replace the respective `YOUR_CASDOOR_CLIENT_ID`
and `YOUR_CASDOOR_CLIENT_SECRET` in the .env file you created.

#### MongoDB User Management Secrets

The MUM plugin stores temporary MongoDB user configs inside Nomad Variables, which Nomad
encrypts at rest. Ensure the Nomad ACL tokens used by the Tasks API can create variables
under the `sep/mum/*` prefix so the plugin can persist short-lived credentials without
writing them to the Tasks database. No additional SEP-specific secret is required.

### Environment

You can categorize settings by environments in settings.yaml:
```yaml
default:
  # defaults settings shared by all environments
development:
  # development settings
production_docker:
  # production settings for Docker deployment
```

To switch environment, use the environment variable `FASTAPI_ENV` or add `FASTAPI_ENV`
to your .env file.

### Database Configuration

SEP supports multiple database engines for different components. Each component (SEP, Inventory, Tasks) can have its own database configuration:

#### SQLite Configuration (Development)
```yaml
SEP:
  DATABASE:
    ENGINE: sqlite  # Database engine: sqlite, mysql, postgresql
    USER: null
    PASSWORD: null
    HOST: ""  # Database host (empty string for SQLite to avoid URL construction issues)
    PORT: null
    NAME: sep.db

INVENTORY:
  DATABASE:
    ENGINE: sqlite
    USER: null
    PASSWORD: null
    HOST: ""
    PORT: null
    NAME: inventory.db

TASKS:
  DATABASE:
    ENGINE: sqlite
    USER: null
    PASSWORD: null
    HOST: ""
    PORT: null
    NAME: tasks.db
```

#### MySQL/MariaDB Configuration
```yaml
SEP:
  DATABASE:
    ENGINE: mysql
    USER: sep_user
    PASSWORD: your_secure_password
    HOST: localhost
    PORT: 3306
    NAME: sep_database
```

#### PostgreSQL Configuration
```yaml
SEP:
  DATABASE:
    ENGINE: postgresql
    USER: sep_user
    PASSWORD: your_secure_password
    HOST: localhost
    PORT: 5432
    NAME: sep_database
```

Supported database engines:
- `sqlite`: SQLite database (default for development)
- `mysql`: MySQL/MariaDB database
- `postgresql`: PostgreSQL database

> [!NOTE]
> For SQLite databases, set `HOST` to an empty string to avoid URL construction issues.

### Syncers

SEP features Inventory syncing with external services and APIs. You can choose the syncers
you want to enable in the SEP.SYNCERS section of the configuration:

```yaml
SEP:
  # ...
  SYNCERS:
    - SYNCER: PMMSyncer
      PMM:
        ENDPOINT: https://127.0.0.1:8443
        VERIFY_SSL: false
```

Syncers may require additional configuration that can be specifically defined in the `settings.yaml`
(like the `PMM` section in the example above) or globally defined through the `SEP.SYNCER_EXTRA_KWARGS`
config (`SEP__SYNCER_EXTRA_KWARGS` for in env settings). Using `SEP__SYNCER_EXTRA_KWARGS`
is ideal when you have a syncer that needs a secret:
```
SEP__SYNCER_EXTRA_KWARGS__PMM__API_KEY=<Your PMM API key)
```

#### PMMSyncer

Sync Nodes and Services with PMM. Requires the `PMM` setting with `ENDPOINT`, `API_KEY`,
and optionally `VERIFY_SSL`, `SSL_CAFILE`, `SSL_KEYFILE`, and `SSL_CERTFILE`.

#### MySQLSyncer

Sync MySQL/MariaDB inventory (schemas and tables). Optional configuration under each `MySQLSyncer` entry in `SEP.SYNCERS`:

- **`IGNORE_SCHEMAS`**: List of schema names to skip during sync (defaults typically include `sys`, `performance_schema`, `mysql`, `information_schema`).
- **`DEFAULT_EXECUTOR_HOST`**: Nomad node name to use when the MySQL service host does not match any Nomad node. Set this when syncing **RDS**, **DBaaS**, or other remote MySQL instances: the sync payload runs on a Nomad client, so you must choose which client can reach the database. The value must match a **node name** (key) returned by **`/api/tasks/hosts/`**—not the node IP or address—otherwise task execution will fail. If unset, the first available Nomad host is used when there is no match.

Credentials are read on the Nomad client from **`~/.my.cnf`** and **`~/.mylogin.cnf`**. For each host the payload connects to, it looks up a login path **by matching the RDS host**: it tries a login path named like the host (e.g. **`host:port`** or **`host_port`** with colon replaced by underscore), then falls back to **`client`**. So for multiple RDS instances with different credentials, create a login path per host in **`~/.mylogin.cnf`** (e.g. **`mysql_config_editor set --login-path=rds-a.region.rds.amazonaws.com:3306 --user=... --password --host=rds-a.region.rds.amazonaws.com --port=3306`**); the payload will use the matching path automatically.

Example for RDS/DBaaS:

```yaml
SEP:
  SYNCERS:
    - SYNCER: MySQLSyncer
      IGNORE_SCHEMAS:
        - sys
        - performance_schema
        - mysql
        - information_schema
      DEFAULT_EXECUTOR_HOST: "ip-10-0-1-5.region.compute.internal"  # Nomad node name from /api/tasks/hosts/ that can reach RDS
```

### SSL Configuration

SEP supports SSL/TLS configuration for secure communications. SSL settings can be configured at different levels:

#### Global SSL Settings
```yaml
SSL_CAFILE: /path/to/ca-certificate.pem  # Global CA certificate file
```

#### Component-specific SSL Settings
```yaml
SEP:
  SSL_KEYFILE: /path/to/sep-key.pem
  SSL_CERTFILE: /path/to/sep-cert.pem

INVENTORY:
  SSL_KEYFILE: /path/to/inventory-key.pem
  SSL_CERTFILE: /path/to/inventory-cert.pem

TASKS:
  SSL_KEYFILE: /path/to/tasks-key.pem
  SSL_CERTFILE: /path/to/tasks-cert.pem
```

#### Nomad SSL Configuration
```yaml
TASKS:
  NOMAD:
    SSL_CAFILE: /path/to/nomad-ca.pem
    SSL_CERTFILE: /path/to/nomad-cert.pem
    SSL_KEYFILE: /path/to/nomad-key.pem
```

SSL certificate files should be in PEM format. Relative paths will be resolved from the project root folder.

##### Getting your PMM API Key

1. In a browser, open PMM's web interface and login (the default credentials are `admin:admin`).
If you followed the Docker tutorial, it should be in https://localhost.

![image](https://github.com/user-attachments/assets/1d521d18-388d-49ea-be32-168d7940748b)

2. Navigate to Configuration > API keys. If you followed the Docker tutorial, it should
be in https://localhost/graph/org/apikeys.

![image](https://github.com/user-attachments/assets/c98792c9-a247-49d7-aafd-c4fcb3523848)

3. Click the **New API key** button to create a new API key. Make sure the **Role** is set to **Admin**.

![image](https://github.com/user-attachments/assets/59a8a2c0-2a5e-4183-a3b9-b3f7f858f9b8)

4. Copy the generated API Key and replace the respective `YOUR_PMM_API_KEY` in your .env file.

![image](https://github.com/user-attachments/assets/a6879771-6350-4505-944a-a5be8183f54c)

## Usage

1. Enter the project folder:
```shell
cd SEP
```

2. Activate your virtualenv:
```shell
source venv/bin/activate
```

3. Start SEP:
```shell
LOGGING=debug python3 -m app.main
```

SEP will be available in http://localhost:8000.

![image](https://github.com/user-attachments/assets/cec67a8e-341a-45d5-9144-e6c24f5128eb)


### Starting Celery with SEP for development

For development environments, you can start the Celery Worker and the Celery Beat with SEP by using the `--start-celery` flag:
```shell
LOGGING=debug python3 -m app.main --start-celery
```

## Alternative: Use Docker Compose

You can also run sep with Docker Compose by following these steps:

1. Enter the project folder:
```shell
cd SEP
```

2. Generate the SSL certificates with the [`generate_certs.sh`](https://github.com/percona/SEP/blob/main/generate_certs.sh) script:
```shell
./generate_certs.sh
```

3. Generate Casdoor's init data with the [`generate_casdoor_init_data.sh`](https://github.com/percona/SEP/blob/main/generate_casdoor_init_data.sh) script:
```shell
./generate_casdoor_init_data.sh
```
You can use the `-p/--password` argument to specify a password for the initial user:
```shell
./generate_casdoor_init_data.sh -p password
```
If no password is specified, a random one will be generated.

By now, your `data` folder should look something like this:
```
data
├── nomad.hcl
├── certs
│   ├── nomad
│   │   ├── global-client-nomad.pem
│   │   ├── global-server-nomad-key.pem
│   │   ├── global-client-nomad-key.pem
│   │   ├── global-client-nomad.p12
│   │   └── global-server-nomad.pem
│   ├── sep-ca-key.pem
│   ├── sep
│   │   ├── localhost-cert-key.pem
│   │   ├── inventory_api-cert-key.pem
│   │   ├── tasks_api-cert.pem
│   │   ├── localhost-cert.pem
│   │   ├── inventory_api-cert.pem
│   │   └── tasks_api-cert-key.pem
│   ├── casdoor
│   │   ├── sep_token_jwt_key.pem
│   │   ├── README.md
│   │   ├── sep_token_jwt_key.key
│   └── sep-ca.pem
├── mime.types
├── casdoor_init_data.json
├── http-tests
│   ├── inventory.http
│   ├── nomad.http
│   ├── task_history.http
│   └── tasks.http
└── nginx.conf
```

4. Add your PMM API key to the `.env.docker` file

By now, a `.env.docker` file should have been created in your current directory.
Open it and replace `REPLACE_WITH_YOUR_PMM_API_KEY` with your actual PMM API key.

5. Start Nomad with the new generated config:
```shell
nomad agent -config /path/to/SEP/data/nomad.hcl
```
Replace `/path/to/SEP` with the path in which the project folder is stored in your computer.

> [!IMPORTANT]
> Make sure you're not running other Nomad instances.

6. Build the Docker Compose services:
```shell
docker compose build
```

7. Start the Docker Compose services:
```shell
docker compose up
```

SEP will be available in https://localhost.
You can stop SEP with CTRL-C and later start it again with `docker compose up`.

## Contributing

See our [CONTRIBUTING](https://github.com/percona/SEP/blob/main/CONTRIBUTING.md) guide.

## Deployment

See our [INSTALLER](https://github.com/percona/SEP/blob/main/INSTALLER.md) guide for deployment instructions.
