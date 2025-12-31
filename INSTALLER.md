# SEP Installer (`sep_installer.sh`)

This repository ships a self-contained installer script (`sep_installer.sh`) that:

- Collects configuration (interactive UI or plain text prompts, or fully non-interactive).
- Generates local TLS material and secrets.
- Renders deployment templates into an install directory.
- Pulls the SEP container image and creates the stack with Docker Compose / Podman Compose.

## Requirements

### Supported platforms

- Linux is the primary target (rootless Podman or Docker).
- Other OSs may work, but are untested.

### Required tools

- bash
- Docker with Compose plugin or Podman + `podman-compose`
- OpenSSL (`openssl`)
  - Sub-commands: `genpkey`, `rsa`, `ecparam`, `req`, `x509`, `rand`
- gzip (`gunzip`)
- GNU sed (`sed`)
- GNU findutils (`find`)
- GNU coreutils(`mktemp`, `chmod`, `mkdir`, `rm`, `cp`, `ls`, `touch`, `cat`, `sleep`, `base64`, `printf`, `test`, `echo`, `true`)

If you run with UI enabled (Textual TUI), you also need:

- Python 3.9+ (`python3`)
- Outbound HTTPS access to `pypi.org` (used by the UI bootstrap check); disable UI with `NO_UI=1` if your environment is offline.

### Permissions

- The install directory (default `~/sep`) must be writable.
- Container engine must be usable by the current user (e.g., Docker group membership or rootless Podman configured).

## Networking requirements

### Host ports

By default, the installer configures:

- HTTPS UI: `8444` (`SEP_HTTPS_PORT`)
- HTTP: `8080` (`SEP_HTTP_PORT`)

Make sure these ports are free on the host before installing or override them with flags.

### Outbound network access

Required for a normal installation:

- Container registry access to pull the SEP image (default `docker.io/percona/percona-sep:v0.9`, which requires a Docker OAT).

Optional (only when UI is enabled):

- `pypi.org` (UI bootstrap vulnerability metadata check)

### External PMM

If you choose to use an existing/external PMM instance (`--use-existent-pmm`), the running SEP stack must be able to reach it over the network.

## Verifying checksums

Before running the installer, you may wish to verify its integrity. The SHA256 checksum of the `sep_installer.sh` file can be found in `sep_installer.sha256` in this repository.

## How to run

Make the script executable and run it:

```bash
chmod +x ./sep_installer.sh
./sep_installer.sh
```

### Typical interactive run

```bash
./sep_installer.sh
```

### Non-interactive (headless) run

Uses defaults plus any flags/env you provide:

```bash
NO_UI=1 ./sep_installer.sh --no-interaction --autostart
```

### Choose a container engine

```bash
./sep_installer.sh --engine podman
```

### Overwrite an existing install directory

```bash
./sep_installer.sh --install-dir "$HOME/sep" --overwrite
```

## UI modes (Textual vs plain text)

The installer supports two interaction styles:

### Textual UI (default when possible)

If:

- stdout is a TTY, and
- `python3` is available, and
- UI bootstrap succeeds

…the installer runs an interactive Textual-based UI (forms, confirmations, progress spinners).

Disable this explicitly with:

```bash
NO_UI=1 ./sep_installer.sh
```

### Plain text mode

If UI is disabled or cannot be loaded, the installer falls back to standard prompts and logs.

## What the installer writes

The install directory defaults to `~/sep` (configurable).

Generated/created artifacts typically include:

- `compose.yaml` (stack definition)
- `settings.yaml`
- `nginx.conf`
- `casdoor_init.json`
- `certs/` (generated TLS material; files are set read-only)
- `.secrets` (generated passwords/tokens; permissions set to `640`)

## Command line arguments and environment variables

The script supports both CLI flags and environment variables. Flags generally take precedence over defaults; environment variables can be used to pre-seed values.

### Core options

| CLI flag | Environment variable | Purpose | Default |
|---|---|---|---|
| `--install-dir DIR` | `INSTALL_DIR` | Where to write rendered configs and secrets | `~/sep` |
| `--engine docker\|podman` | `CONTAINER_ENGINE` | Container engine used for `pull` and `compose` | `docker` |
| `--docker-token TOKEN` | `DOCKER_TOKEN` | Token for registry login when needed | empty |
| `--overwrite` | `OVERWRITE_INSTALL_DIR=1` | Don’t prompt if install dir exists and is non-empty | `0` |
| `--autostart` | `AUTOSTART=1` | Start stack after installation | `0` |
| `--no-interaction` (`--headless`, `--yes`, `-y`) | `NO_INTERACTION=1` | Skip prompts and use defaults/flags | auto (TTY → 0, non-TTY → 1) |

### Networking / ports

| CLI flag | Environment variable | Purpose | Default |
|---|---|---|---|
| `--http-port PORT` | `SEP_HTTP_PORT` | Host HTTP port (if enabled in templates) | `8080` |
| `--https-port PORT` | `SEP_HTTPS_PORT` | Host HTTPS port (main UI) | `8444` |

### Image selection

These do not currently have CLI flags; set them via environment variables:

| Environment variable | Purpose | Default |
|---|---|---|
| `SEP_IMAGE_NAME` | SEP container image name | `docker.io/percona/percona-sep` |
| `SEP_IMAGE_TAG` | SEP container image tag | `v0.9` |

### PMM selection and credentials

| CLI flag | Environment variable | Purpose | Default |
|---|---|---|---|
| `--create-pmm-container` | `CREATE_PMM_CONTAINER=1` | Include a PMM container in the stack | `0` |
| `--use-existent-pmm` | `CREATE_PMM_CONTAINER=0` | Use an external/existing PMM (removes PMM from stack) | `0` |
| `--pmm-user USER` | `SEP_PMM_URL_AUTH_ACCOUNT_USER` | PMM username (Nomad auth) | empty |
| `--pmm-pass PASS` | `SEP_PMM_URL_AUTH_ACCOUNT_PASS` | PMM password (Nomad auth) | empty |
| `--pmm-token TOKEN` | `SEP_PMM_URL_AUTH_TOKEN` | PMM service account token (inventory sync) | empty |

Related environment variables (advanced):

| Environment variable | Purpose | Default |
|---|---|---|
| `SEP_PMM_PUBLIC_HOST` | PMM host address used in rendered config | `127.0.0.1` |
| `SEP_PMM_PORT` | PMM port | `8443` |
| `SEP_PMM_FRONTEND` | PMM base URL | `https://${SEP_PMM_PUBLIC_HOST}` |
| `SEP_PMM_NOMAD_DATA_DIR` | Nomad data directory (PMM-related) | `${INSTALL_DIR}/nomad_data` |
| `SEP_PMM_CONTAINER_NAME` | PMM container name | `sep-pmm-1` |
| `SEP_PMM_URL_AUTH_ACCOUNT` | Combined `user:pass` form (optional) | empty |

### Plugins

| CLI flag | Environment variable | Purpose | Default |
|---|---|---|---|
| `--plugins LIST` | `SEP_ENABLED_PLUGINS` | Comma-separated plugin internal names | `schema_change,archive,backups,checksums,snippets` |

Available plugin names:

- `schema_change`
- `archive`
- `backups`
- `checksums`
- `snippets`
- `task_manager`
- `mongodb_backups`

### UI and logging controls

These are environment variables only:

| Environment variable | Purpose | Default |
|---|---|---|
| `NO_UI=1` | Force plain text mode (disable Textual UI) | auto |
| `NO_CLEAR=1` | Don’t clear the terminal between screens | auto |
| `TEXTUAL_THEME` | Textual UI theme | `gruvbox` |
| `DEBUG=1` | Enables shell tracing (`set -x`) | `0` |

## After installation

The installer prints the stack command it uses (Docker Compose or Podman Compose) and shows how to:

- Start the stack (if not using `--autostart`)
- View logs
- Stop the stack

Credentials are stored in:

```bash
${INSTALL_DIR}/.secrets
```

Protect this file appropriately and avoid committing it anywhere.
