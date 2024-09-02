# SEP - Services Enablement Platform

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
--publish 443:443 \
--network host \
--volume pmm-data:/srv \
--name pmm-server \
percona/pmm-server:2
```

- [Percona Toolkit](https://www.percona.com/percona-toolkit)
- [Nomad](https://developer.hashicorp.com/nomad/tutorials/get-started/gs-install)

Make sure your Nomad agent has the name `pmm-server`. For the purpose of development, you can run Nomad with
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

3. Download your Casdoor certificate

In Casdoor's web interface, navigate to Identity > Certs > cert-built-in
(should be in [this link](http://localhost:9999/certs/admin/cert-built-in)) and click on
the **Download certificate** button. Save the `token_jwt_key.pem` file in the **SEP/data** folder.

![image](https://github.com/user-attachments/assets/fbacba5d-4f08-4331-b54f-985015f750ac)

> [!TIP]
> You can store your cert file with any other name or in any other folder by adding the
> setting `CERTIFICATE_PATH` in the `CASDOOR` section in `settings.yaml`, or the
> `CASDOOR__CERTIFICATE_PATH` in your env vars/.env. 

4. Create a .env file in the project root folder to store your secrets.
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
| CASDOOR__CERTIFICATE_PATH  | all       | yes      | N/A                                                 | data/token_jwt_key.pem                         |
| CASDOOR__ORGANIZATION_NAME | all       | no       | built-in                                            | N/A                                            |
| CASDOOR__APPLICATION_NAME  | all       | no       | app-built-in                                        | N/A                                            |
| AUTH_USER_MODEL            | all       | no       | app.core.auth.models.BaseUser                       | app.models.CasdoorUser                         |
| LOGGING                    | all       | no       | WARNING                                             | N/A                                            |
| BACKEND_CORS_ORIGINS       | all       | no       | []                                                  | [http://localhost:8000, http://127.0.0.1:8000] |
| PMM__ENDPOINT              | inventory | yes      | N/A                                                 | https://127.0.0.1                              |
| PMM__VERIFY_SSL            | inventory | no       | True                                                | False                                          |
| NOMAD__ENDPOINT            | tasks     | yes      | N/A                                                 | http://127.0.0.1:4646                          |
| NOMAD__SECURE              | tasks     | no       | False                                               | N/A                                            |
| NOMAD__TIMEOUT             | tasks     | no       | 10                                                  | N/A                                            |
| NOMAD__VERIFY              | tasks     | no       | False                                               | N/A                                            |
| EXECUTE_MODE               | tasks     | no       | background                                          | N/A                                            |
| INVENTORY_ENDPOINT         | sep       | yes      | N/A                                                 | http://localhost:8000/api/inventory            |
| TASKS_ENDPOINT             | sep       | yes      | N/A                                                 | http://localhost:8000/api/tasks                |
| OAUTH__REDIRECT_URI        | sep       | yes      | N/A                                                 | http://localhost:8000/oauth/callback           |
| OAUTH__POST_LOGIN_URI      | sep       | no       | /                                                   | N/A                                            |
| OAUTH__AUTH_LINK           | sep       | no       | CasdoorOptions.SYNC_SDK.get_auth_link(REDIRECT_URI) | N/A                                            |
| OAUTH__COOKIE_NAME         | sep       | no       | authToken                                           | casdoorToken                                   |
| TEMPLATES_DIR              | sep       | no       | templates                                           | templates                                      |
| STATIC_DIR                 | sep       | no       | static                                              | N/A                                            |


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

SEP needs some keys and secrets to interact with Casdoor and PMM. They are:
- `CASDOOR__CLIENT_ID`
- `CASDOOR__CLIENT_SECRET`
- `PMM__API_KEY`

You can create a basic .env file template by running the following command in the project root folder:
```shell
echo -e "CASDOOR__CLIENT_ID=YOUR_CASDOOR_CLIENT_ID\nCASDOOR__CLIENT_SECRET=YOUR_CASDOOR_CLIENT_SECRET\nPMM__API_KEY=YOUR_PMM_API_KEY" > .env
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

#### Getting your PMM API Key

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
python3 -m app.main --logging=debug
```

SEP will be available in http://localhost:8000.

![image](https://github.com/user-attachments/assets/cec67a8e-341a-45d5-9144-e6c24f5128eb)
