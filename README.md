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
* [Usage](#usage)
* [Alternative: Use Docker Compose](#alternative-use-docker-compose)

## Prerequisites

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

4. Download your Casdoor certificate

In Casdoor's web interface, navigate to Identity > Certs > cert-built-in
(should be in [this link](http://localhost:9999/certs/admin/cert-built-in)) and click on
the **Download certificate** button. Save the `token_jwt_key.pem` file in the **SEP/data/certs/casdoor** folder.

![image](https://github.com/user-attachments/assets/fbacba5d-4f08-4331-b54f-985015f750ac)

> [!TIP]
> You can store your cert file with any other name or in any other folder by adding the
> setting `CERTIFICATE_PATH` in the `CASDOOR` section in `settings.yaml`, or the
> `CASDOOR__CERTIFICATE_PATH` in your env vars/.env.

5. Add your Redirect URL to the Casdoor application

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
3. settings.yaml

The [settings.yaml](https://github.com/percona/SEP/blob/main/settings.yaml) has base settings that you can (but don't need to) change.

Some settings are app-specific and you might not need them for running another app.
These are the possible settings you can have, per app:


| Name                       | App       | Required | Default                                             | settings.yaml                                  |
|----------------------------|-----------|----------|-----------------------------------------------------|------------------------------------------------|
| BASE_URI                   | all       | yes      | N/A                                                 | N/A                                            |
| CASDOOR__ENDPOINT          | all       | yes      | N/A                                                 | N/A                                            |
| CASDOOR__CERTIFICATE_PATH  | all       | yes      | N/A                                                 | data/certs/token_jwt_key.pem                   |
| CASDOOR__ORGANIZATION_NAME | all       | no       | built-in                                            | N/A                                            |
| CASDOOR__APPLICATION_NAME  | all       | no       | app-built-in                                        | N/A                                            |
| AUTH_USER_MODEL            | all       | no       | app.core.auth.models.BaseUser                       | app.models.CasdoorUser                         |
| LOGGING                    | all       | no       | WARNING                                             | N/A                                            |
| BACKEND_CORS_ORIGINS       | all       | no       | []                                                  | [http://localhost:8000, http://127.0.0.1:8000] |
| CELERY__CELERY_BROKER_URL  | all       | yes      | static                                              | "redis://localhost:6379/0"                     |
| CELERY_RESULT_BACKEND      | all       | yes      | static                                              | "redis://localhost:6379/0"                     |
| TASKS__NOMAD__ENDPOINT     | tasks     | yes      | N/A                                                 | http://127.0.0.1:4646                          |
| TASKS__NOMAD__SECURE       | tasks     | no       | False                                               | N/A                                            |
| TASKS__NOMAD__TIMEOUT      | tasks     | no       | 10                                                  | N/A                                            |
| TASKS__NOMAD__VERIFY       | tasks     | no       | False                                               | N/A                                            |
| TASKS__EXECUTE_MODE        | tasks     | no       | background                                          | N/A                                            |
| TASKS__DATABASE__ENGINE    | tasks     | no       | sqlite                                              | N/A                                            |
| TASKS__DATABASE__NAME      | tasks     | no       | tasks.db                                            | N/A                                            |
| TASKS__DATABASE__USER      | tasks     | no       | N/A                                                 | N/A                                            |
| TASKS__DATABASE__PASSWORD  | tasks     | no       | N/A                                                 | N/A                                            |
| TASKS__DATABASE__HOST      | tasks     | no       | N/A                                                 | N/A                                            |
| TASKS__DATABASE__PORT      | tasks     | no       | N/A                                                 | N/A                                            |
| SEP__INVENTORY_ENDPOINT    | sep       | yes      | N/A                                                 | http://localhost:8000/api/inventory            |
| SEP__TASKS_ENDPOINT        | sep       | yes      | N/A                                                 | http://localhost:8000/api/tasks                |
| SEP__OAUTH__REDIRECT_URI   | sep       | yes      | N/A                                                 | http://localhost:8000/oauth/callback           |
| SEP__OAUTH__POST_LOGIN_URI | sep       | no       | /                                                   | N/A                                            |
| SEP__OAUTH__AUTH_LINK      | sep       | no       | CasdoorOptions.SYNC_SDK.get_auth_link(REDIRECT_URI) | N/A                                            |
| SEP__SESSION__COOKIE_NAME  | sep       | no       | authToken                                           | casdoorToken                                   |
| SEP__TEMPLATES_DIR         | sep       | no       | templates                                           | templates                                      |
| SEP__STATIC_DIR            | sep       | no       | static                                              | N/A                                            |


Path settings (`CASDOOR__CERTIFICATE_PATH`, `TEMPLATES_DIR`, `STATIC_DIR`, etc.) may have
relative or absolute values. Relative paths will be resolved from the project root folder.

> [!CAUTION]
> *Do not store secrets in settings.yaml, as the file is shared in the git repository.
> See the [secrets section](#secrets) of the README for more details.

### Plugins

SEP works with modular plugins. Plugins are FastAPI routers that will be added to the application
according to defined settings. Each plugin must have their own module in `app.sep.plugins`
with a `router` inside. An example of a plugin can be found in the base settings.yaml:

```yaml
PLUGINS:
  - NAME: Schema Change
    MODULE_NAME: alters
    URI_PATH: /alters
    CSS_CLASS: alters
```

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

### Environment

You can categorize settings by environments in settings.yaml:
```yaml
default:
  # defaults settings shared by all environments
development:
  # development settings
production:
  # production settings
```

To switch environment, use the environment variable `FASTAPI_ENV` or add `FASTAPI_ENV`
to your .env file.

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

### Celery and Celery RedBeat Scheduler
1. Docker setup

```yaml
services:
  redis:
    image: redis
    ports:
      - "6379:6379"
      
  redis-commander:
    container_name: redis-commander
    hostname: redis-commander
    image: rediscommander/redis-commander:latest
    restart: always
    environment:
      - REDIS_HOSTS=local:redis:6379
    ports:
      - "8080:8081"
```

- **Redis**: This service runs the Redis server on port `6379`, which is the default port used by Celery for the broker and result backend.
- **Redis Commander**: This service provides a web interface to interact with Redis, accessible at `http://localhost:8080`. It allows you to view and manage your Redis data easily.
2. Running Celery Worker
```shell
celery -A app.main.celery worker --loglevel=info
```

3. Running the Celery Beat Scheduler
```shell
celery -A app.main.celery beat -S redbeat.RedBeatScheduler --loglevel=info
```

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
