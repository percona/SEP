# SEP - Services Enablement Platform

SEP (Services Enablement Platform) is a modular platform for integrating and managing various services. It provides a web-based UI for interacting with different plugins and a backend for orchestrating tasks.

## Table of Contents

*   [Getting Started](#getting-started)
    *   [Prerequisites](#prerequisites)
    *   [Local Development Setup](#local-development-setup)
    *   [Docker Compose Setup](#docker-compose-setup)
*   [Configuration](#configuration)
    *   [Configuration Loading](#configuration-loading)
    *   [Environments](#environments)
    *   [Core Configuration](#core-configuration)
    *   [Database](#database-configuration)
    *   [Plugins](#plugins)
    *   [Syncers](#syncers)
    *   [Secrets Management](#secrets-management)
*   [Running SEP](#running-sep)
*   [Contributing](#contributing)

## Getting Started

This section will guide you through setting up SEP on your local machine.

### Prerequisites

Before you begin, ensure you have the following installed:

*   **Python:** >=3.11.9, !=3.12.0, !=3.12.1, !=3.12.2, <3.14. See `pyproject.toml` for the exact version requirements.
*   **Docker:** For running services like Casdoor and PMM.
*   **Nomad:** For task orchestration. Installation instruction is [here](https://developer.hashicorp.com/nomad/install).
*   **Percona Toolkit:** A collection of advanced command-line tools for MySQL.
*   **Celery:** For running background tasks.

You will also need access to:
*   **Casdoor:** An open-source Identity and Access Management (IAM) platform.
*   **PMM (Percona Monitoring and Management):** An open-source database monitoring and management tool.

### Local Development Setup

Follow these steps to run SEP locally for development.

#### 1. Set up Dependencies

**A. Start Casdoor**

You can start Casdoor on port 9999 using Docker:
```shell
docker run --detach --name casdoor \
--volume casdoor-data:/var/lib/mysql:z,rw \
--publish 9999:8000/tcp \
casbin/casdoor-all-in-one
```
> The default credentials are `admin:123`. You can access it at `http://localhost:9999`.

**B. Start PMM**

You can start PMM using Docker:
```shell
curl -fsSL https://www.percona.com/get/pmm | /bin/bash
```
> The default credentials are `admin:admin`. You can access it at `https://localhost`.

**C. Start Nomad**
For development, you can run Nomad in dev mode:
```shell
sudo nomad agent -node="pmm-server" -dev \
        -bind 0.0.0.0 \
        -network-interface='{{ GetDefaultInterfaces | attr "name" }}'
```

#### 2. Prepare the SEP Environment

**A. Clone the Repository**
```shell
git clone https://github.com/percona/SEP.git
cd SEP
```

**B. Create a Virtual Environment**

This command creates a Python virtual environment at `./venv` and installs the required dependencies from `pyproject.toml`.
```shell
make venv
source venv/bin/activate
```
> **Note:** If you are using the Fish shell, activate the environment with `source venv/bin/activate.fish`.

**C. Configure Secrets**

SEP requires secrets to connect to Casdoor. Create a `.env` file in the project root:
```shell
echo -e "CASDOOR__CLIENT_ID=
CASDOOR__CLIENT_SECRET=" > .env
```
Now, get your Casdoor `Client ID` and `Client Secret`:
1.  Open Casdoor at `http://localhost:9999`.
2.  Log in with `admin:123`.
3.  Navigate to **Applications** and click on **app-built-in**.
4.  Copy the `Client ID` and `Client Secret` and paste them into your `.env` file.

![Casdoor Application Page](https://github.com/user-attachments/assets/2b95de9d-33ce-4f60-9457-f89e7c6ce619)

**D. Set up Databases**

Create the necessary databases for SEP and its components:
```shell
make migrate
```

**E. Configure Redirect URL in Casdoor**

You need to tell Casdoor where to redirect users after they log in.
1.  In Casdoor, go to the **app-built-in** application settings.
2.  Scroll down to **Redirect URLs**.
3.  Add the following URLs:
    *   `http://localhost:8000/oauth/callback`
    *   `http://127.0.0.1:8000/oauth/callback`

![Casdoor Redirect URLs](https://github.com/user-attachments/assets/8a562b77-00c7-4192-bba3-d22e3514766f)

**F. Start Celery**

Start the Celery worker and beat for background task processing.


```shell
# Start the worker
celery -A app.tasks.celery worker -l info

# Start the beat scheduler
celery -A app.tasks.celery beat -S sqlalchemy --loglevel=info
```
> **Tip:** For development, you can also start Celery directly with the main application. See the [Usage section](#usage).

#### 3. Run SEP

You are now ready to start the application!
```shell
LOGGING=debug python3 -m app.main
```

SEP will be available at `http://localhost:8000`.

### Docker Compose Setup

For a more production-like environment, you can use Docker Compose.

1.  **Clone the Repository**
    ```shell
    git clone https://github.com/percona/SEP.git
    cd SEP
    ```

2.  **Generate SSL Certificates**
    ```shell
    ./generate_certs.sh
    ```

3.  **Generate Casdoor Init Data**
    This script prepares initial data for Casdoor.
    ```shell
    ./generate_casdoor_init_data.sh
    ```
    You can set a password for the initial user with the `-p` flag:
    ```shell
    ./generate_casdoor_init_data.sh -p your_password
    ```
    If you don't provide a password, a random one will be generated.

4.  **Configure PMM API Key**
    A `.env.docker` file has been created. Open it and replace `REPLACE_WITH_YOUR_PMM_API_KEY` with your actual PMM API key. See [Getting your PMM API Key](#getting-your-pmm-api-key) for instructions.

5.  **Start Nomad**
    Start a Nomad agent with the generated configuration file.
    ```shell
    nomad agent -config /path/to/SEP/data/nomad.hcl
    ```
    > **Important:** Ensure no other Nomad instances are running.

6.  **Build and Run with Docker Compose**
    ```shell
    docker compose build
    docker compose up
    ```

SEP will be available at `https://localhost`.

---

## Configuration

SEP is configured through a combination of environment variables, a `.env` file, and a `settings.yaml` file.

### Configuration Loading

Settings are loaded in the following order of priority:
1.  **Environment Variables:** Highest priority. (e.g., `CASDOOR__ENDPOINT=...`)
2.  **.env File:** Loads environment variables from a file (defaults to `.env`).
3.  **settings.yaml:** The base configuration file.

You can specify a different `.env` file or settings file with the `ENV_FILE` and `SETTINGS_FILE` environment variables.

### Environments

You can define different configuration profiles (e.g., `development`, `production`) within `settings.yaml`. Use the `FASTAPI_ENV` environment variable to switch between them.

```yaml
default:
  # Settings shared by all environments
development:
  # Development-specific settings
production_docker:
  # Settings for Docker production deployment
```

### Core Configuration

The `settings.yaml` file contains base settings. Here are some of the key settings:

| Setting                    | Description                                       | Default                              |
| -------------------------- | ------------------------------------------------- | ------------------------------------ |
| `ALLOWED_HOSTS`            | List of allowed hostnames.                        | `["localhost", "127.0.0.1"]`         |
| `CASDOOR__ENDPOINT`        | The URL of your Casdoor instance.                 | `http://localhost:9999`              |
| `CELERY__BROKER_URL`       | The connection URL for your Celery broker.        | `filesystem://`                      |
| `TASKS__NOMAD__ENDPOINT`   | The URL for the Nomad API.                        | `http://127.0.0.1:4646`              |
| `SEP__INVENTORY_ENDPOINT`  | The endpoint for the SEP inventory API.           | `http://localhost:8000/api/inventory`|
| `SEP__TASKS_ENDPOINT`      | The endpoint for the SEP tasks API.               | `http://localhost:8000/api/tasks`    |

> **Caution:** Do not store secrets in `settings.yaml`. Use a `.env` file or environment variables for sensitive data.

### Database Configuration

Each component (SEP, Inventory, Tasks) can have its own database configuration. Supported engines are `sqlite`, `mysql`, and `postgresql`.

**Example (SQLite):**
```yaml
TASKS:
  DATABASE:
    ENGINE: sqlite
    NAME: tasks.db
```

**Example (MySQL):**
```yaml
TASKS:
  DATABASE:
    ENGINE: mysql
    USER: db_user
    PASSWORD: your_password
    HOST: localhost
    PORT: 3306
    NAME: tasks_db
```

### Plugins

SEP has a modular architecture based on plugins. You can enable and configure plugins in `settings.yaml`.

```yaml
PLUGINS:
  - NAME: Schema Change
    MODULE_NAME: alters
    URI_PATH: /alters
    CSS_CLASS: alters
  # ... more plugins
```

### Syncers

Inventory can be synced with external services via "Syncers".

```yaml
SEP:
  SYNCERS:
    - SYNCER: PMMSyncer
      PMM:
        ENDPOINT: https://127.0.0.1:8443
        VERIFY_SSL: false
```

#### PMMSyncer

This syncer syncs nodes and services from a PMM instance. It requires `ENDPOINT` and `API_KEY` (as a secret).

##### Getting your PMM API Key

1.  Open PMM and log in.
2.  Go to **Configuration > API keys**.
3.  Click **New API key**.
4.  Set the **Role** to **Admin** and create the key.
5.  Copy the generated key. You will use this as a secret (e.g., `SEP__SYNCER_EXTRA_KWARGS__PMM__API_KEY`).

### Secrets Management

Secrets like API keys and client secrets should be managed outside of version control.

*   `CASDOOR__CLIENT_ID`: The client ID for your Casdoor application.
*   `CASDOOR__CLIENT_SECRET`: The client secret for your Casdoor application.
*   `SEP__SYNCER_EXTRA_KWARGS__PMM__API_KEY`: The API key for PMM.

Store these in a `.env` file or as environment variables.

---

## Running SEP

1.  **Navigate to the project directory:**
    ```shell
    cd SEP
    ```

2.  **Activate the virtual environment:**
    ```shell
    source venv/bin/activate
    ```

3.  **Start the application:**
    ```shell
    LOGGING=debug python3 -m app.main
    ```

    SEP will be available at `http://localhost:8000`.

    ![SEP Homepage](https://github.com/user-attachments/assets/cec67a8e-341a-45d5-9144-e6c24f5128eb)

4.  **Start with Celery (for development):**
    To run the Celery worker and beat along with the main app, use the `--start-celery` flag.
    ```shell
    LOGGING=debug python3 -m app.main --start-celery
    ```

## Contributing

We welcome contributions! Please see our [CONTRIBUTING.md](https://github.com/percona/SEP/blob/main/CONTRIBUTING.md) guide for more details on how to get started.