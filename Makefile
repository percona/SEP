# vim: ts=8:sw=8:ft=make:noai:noet

SHELL=env bash

PYTHON?=python3
RELEASE_VER?=HEAD
# Pin Poetry so the bootstrap doesn't pull a fresh release whose transitive
# deps (e.g. virtualenv) are then filtered out by solver.min-release-age=7
# during the project's plugin resolve.
POETRY_VERSION?=2.4.0
ifdef VIRTUAL_ENV
    VENV=${VIRTUAL_ENV}
else
    VENV?=venv
endif
VENV_BIN?="${VENV}/bin"
ifdef POETRY
	START_PKGS=pip wheel
	VIRTUAL_ENV=$$("${POETRY}" env info --path)
	VENV=${VIRTUAL_ENV}
	VENV_BIN="${VENV}/bin"
else
	START_PKGS=pip wheel poetry==${POETRY_VERSION}
	POETRY="${VENV_BIN}/poetry"
endif
PIP?="${VENV_BIN}/pip"
APPS=tasks inventory sep
PYTEST_WORKERS?=auto

# WeasyPrint loads native libs (libgobject-2.0, libpango, libcairo) at import
# time. Homebrew installs them under /opt/homebrew/lib (Apple Silicon) or
# /usr/local/lib (Intel) — neither is on dyld's default search path. macOS SIP
# also strips DYLD_* from any env inherited by /usr/bin/make, so the export
# must happen inside each recipe shell. No-op on Linux/CI/Docker. (SEP-1125)
DARWIN_DYLD = if [ "$$(uname -s)" = "Darwin" ]; then \
		for d in /opt/homebrew/lib /usr/local/lib; do \
			if [ -d "$$d" ]; then \
				export DYLD_FALLBACK_LIBRARY_PATH="$$d:$${DYLD_FALLBACK_LIBRARY_PATH}"; \
				break; \
			fi; \
		done; \
	fi;

venv: pyproject.toml poetry.lock
	@[ ! -z "${VIRTUAL_ENV}" ] || [ -d "venv" ] || "${PYTHON}" -m venv "${VENV}"
	@"${PIP}" install --no-cache ${START_PKGS};
	@source "${VENV_BIN}"/activate; "${POETRY}" install --all-extras --all-groups

build: venv app/
	@source "${VENV_BIN}"/activate; "${POETRY}" build --format wheel --output dist

pack:
ifndef BUNDLE
	@echo Exporting bundle
	@git archive --output=bundle.tgz --format=tar.gz "${RELEASE_VER}" app snippets static templates
else
	@echo Copying custom bundle "${BUNDLE}"
	@cp -a "${BUNDLE}" bundle.tgz
endif

builder:
	@podman image exists "sep:builder" && podman image rm "sep:builder"
	@buildah build -f Containerfile.base --compress --force-rm --squash --no-cache --format oci --memory 100M --isolation rootless --tag "sep:builder"

image: pack
	@podman image exists "sep:${RELEASE_VER}" && podman image rm "sep:${RELEASE_VER}" || true
	@buildah build -f Containerfile --compress --force-rm --squash --no-cache --format oci --memory 100M --isolation rootless --tag "sep:${RELEASE_VER}"

format: venv
	@"${VENV_BIN}"/ruff format .
	@"${VENV_BIN}"/djlint . --reformat

ruff: venv
	@"${VENV_BIN}"/ruff check .
	@"${VENV_BIN}"/ruff format --check .

djlint: venv
	@"${VENV_BIN}"/djlint .
	@"${VENV_BIN}"/djlint . --check

lint: ruff djlint

audit: bandit pip-audit

# python.org macOS builds ship without etc/openssl/cert.pem until you run
# "Install Certificates.command"; urllib then fails for hooks that fetch remotes.
run-pre-commit: venv
	@SSL_CERT_FILE=$$("${VENV_BIN}"/python -c 'import certifi; print(certifi.where())') \
		"${VENV_BIN}"/pre-commit run --all-files

# Local development only; production startup uses container/entrypoint paths.
dev-backend: venv
	@$(DARWIN_DYLD) "${VENV_BIN}"/python -m app.main $(if $(START_CELERY),--start-celery,)

# Local development only; production frontend startup stays outside Make.
dev-frontend:
	@cd frontend && pnpm dev

pip-audit: venv
	@"${POETRY}" run pip-audit --verbose --progress-spinner=off \
		$$($(PYTHON) -c "import tomllib,pathlib;c=tomllib.loads(pathlib.Path('pyproject.toml').read_text());print(' '.join(f'--ignore-vuln {v}' for v in c.get('tool',{}).get('pip-audit',{}).get('ignore-vulnerabilities',[])))" 2>/dev/null)

bandit: venv
	@"${VENV_BIN}"/bandit -c pyproject.toml -r app

makemigrations: venv alembic.ini app/tasks/models.py app/inventory/models.py app/sep/models.py
	@for app in $(APPS); do \
		capitalized=$$(echo $$app | sed 's/^./\U&/'); \
		echo "Checking migrations for $$capitalized"; \
		"${VENV_BIN}"/alembic --name $$app check > alembic_check.log 2>&1 || { \
			if grep -q "Target database is not up to date" alembic_check.log; then \
				echo "Error: $$capitalized database is not up to date"; \
				echo "Error:   Run 'make migrate' to apply the migrations before making new migrations."; \
				rm alembic_check.log; \
				exit 1; \
			elif grep -q "New upgrade operations detected" alembic_check.log; then \
				echo "New upgrade operations detected for $$capitalized. Creating migration."; \
				read -p "Enter description for new $$capitalized Migration: " desc; \
				if [ "$$app" = "sep" ]; then \
					extra_args="--head=sep_main@head"; \
				else \
					extra_args=""; \
				fi; \
				"${VENV_BIN}"/alembic --name $$app revision --autogenerate $$extra_args -m "$$desc"; \
				rm alembic_check.log; \
				continue; \
			else \
				cat alembic_check.log; \
				rm alembic_check.log; \
				exit 1; \
			fi \
		}; \
		rm alembic_check.log; \
		echo "No new upgrade operations detected for $$capitalized"; \
	done

makemigrations-plugin: venv alembic.ini
ifndef PLUGIN
	$(error PLUGIN is required. Usage: make makemigrations-plugin PLUGIN=<plugin-name>)
endif
	@read -p "Enter description for new $(PLUGIN) plugin migration: " desc; \
	"${VENV_BIN}"/alembic --name sep revision --autogenerate --head=$(PLUGIN)@head -m "$$desc"

migrate: venv alembic.ini app/tasks/migrations/versions app/inventory/migrations/versions app/sep/migrations/versions
	@for app in $(APPS); do \
		"${VENV_BIN}"/alembic --name $$app upgrade heads; \
	done

checkmigrations: migrate
	@ret=0; \
	for app in $(APPS); do \
	  echo "Checking migrations for $$app"; \
	  "${VENV_BIN}"/alembic --name $$app check || ret=1; \
	done; \
	if [ $$ret -ne 0 ]; then \
	  echo "Error: One or more migration checks failed."; \
	  exit $$ret; \
	fi
	@echo "All migration checks passed."

test: venv
	@$(DARWIN_DYLD) "${VENV_BIN}"/pytest -v -r a -n ${PYTEST_WORKERS} --cov=app tests/

changelog-add:
ifndef TICKET
	$(error TICKET is required. Usage: make changelog-add TICKET=SEP-XXX SECTION=added MSG="description")
endif
ifndef SECTION
	$(error SECTION is required. Usage: make changelog-add TICKET=SEP-XXX SECTION=added MSG="description")
endif
ifndef MSG
	$(error MSG is required. Usage: make changelog-add TICKET=SEP-XXX SECTION=added MSG="description")
endif
	@$(PYTHON) scripts/changelog.py add --ticket "$(TICKET)" --section "$(SECTION)" --message "$(MSG)" $(if $(FORCE),--force,)

changelog-check:
	@$(PYTHON) scripts/changelog.py check

changelog-list:
	@$(PYTHON) scripts/changelog.py list

SIGN_FLAG := $(if $(SIGN_VIA_API),--sign-via-github-api,)
PUSH_IMAGE_DOCKER ?= true

release-prep:
ifndef VERSION
	$(error VERSION is required. Usage: make release-prep VERSION=X.Y.Z)
endif
	@$(PYTHON) scripts/release.py prep --version "$(VERSION)" $(SIGN_FLAG)

release-rc:
ifndef VERSION
	$(error VERSION is required. Usage: make release-rc VERSION=X.Y.Z RC=N)
endif
ifndef RC
	$(error RC is required. Usage: make release-rc VERSION=X.Y.Z RC=N)
endif
	@$(PYTHON) scripts/release.py rc --version "$(VERSION)" --rc "$(RC)" $(SIGN_FLAG)

release-stable:
ifndef VERSION
	$(error VERSION is required. Usage: make release-stable VERSION=X.Y.Z)
endif
	@$(PYTHON) scripts/release.py stable --version "$(VERSION)" $(SIGN_FLAG)

trigger-jenkins:
ifndef TAG
	$(error TAG is required. Usage: make trigger-jenkins TAG=vX.Y.Z [PUSH_IMAGE_DOCKER=false] [WEBHOOK_URL_ENV=... WEBHOOK_AUTH_ENV=...])
endif
	@set -euo pipefail; \
	if [ -n "$${JENKINS_URL:-}" ] && [ -n "$${JENKINS_USER:-}" ] && [ -n "$${JENKINS_API_TOKEN:-}" ]; then \
		echo "==> Triggering Jenkins release build for $(TAG)..."; \
		if curl -sSf -k -X POST "$${JENKINS_URL}/job/SEP/job/Release/buildWithParameters" \
			-u "$${JENKINS_USER}:$${JENKINS_API_TOKEN}" \
			--data-urlencode "releaseTag=$(TAG)" \
			--data-urlencode "notifySlack=true" \
			--data-urlencode "pushImage=true" \
			--data-urlencode "pushImageDocker=$(PUSH_IMAGE_DOCKER)" 2>&1; then \
			echo "    Jenkins build triggered successfully."; \
			if [ -n "$(WEBHOOK_URL_ENV)" ] && [ -n "$(WEBHOOK_AUTH_ENV)" ]; then \
				$(PYTHON) scripts/post_jira_webhook.py \
					--url-env "$(WEBHOOK_URL_ENV)" \
					--auth-env "$(WEBHOOK_AUTH_ENV)" \
					--version-tag "$(TAG)" || true; \
			fi; \
		else \
			echo "    Warning: Failed to trigger Jenkins build. Trigger it manually."; \
		fi; \
	else \
		echo "Note: JENKINS_URL/JENKINS_USER/JENKINS_API_TOKEN not all set, skipping Jenkins trigger."; \
	fi

.PHONY: venv build pack builder image format ruff djlint lint audit run-pre-commit dev-backend dev-frontend pip-audit bandit makemigrations makemigrations-plugin migrate checkmigrations test release-prep release-rc release-stable trigger-jenkins changelog-add changelog-check changelog-list
