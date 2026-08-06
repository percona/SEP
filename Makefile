# vim: ts=8:sw=8:ft=make:noai:noet

SHELL=env bash

PYTHON?=python3
RELEASE_VER?=HEAD
# Pin Poetry and pre-install the required plugin via pip. Without the plugin
# pre-installed, `poetry install` runs an auto-resolve to add it, which racks
# the bootstrap-fresh transitive deps (e.g. virtualenv) against the project's
# solver.min-release-age=7 and fails ("virtualenv 21.3.3 doesn't match any
# versions"). Pre-installing means Poetry sees the plugin in its env and skips
# the resolve entirely.
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
	START_PKGS=pip wheel poetry==${POETRY_VERSION} poetry-plugin-export
	POETRY="${VENV_BIN}/poetry"
endif
PIP?="${VENV_BIN}/pip"
APPS=tasks inventory sep
PYTEST_WORKERS?=auto
# COV=0 drops --cov=app (and the fail_under coverage gate) so a local run skips
# the coverage instrumentation tax; CI and coverage-main keep the default COV=1.
COV?=1
PYTEST_PATHS?=tests/
PYTEST_MARKERS?=

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

# docker format, not oci: OCI silently discards the HEALTHCHECK instruction
image-sidecar: pack
	@podman image exists "sep:${RELEASE_VER}-sidecar" && podman image rm "sep:${RELEASE_VER}-sidecar" || true
	@buildah build -f sidecar/Containerfile.sidecar --compress --force-rm --squash --no-cache --format docker --memory 100M --isolation rootless --tag "sep:${RELEASE_VER}-sidecar"

# The app-restricted PMM-embedded variant: the side-car recipe with the app
# strip switched on. Which apps survive is settings.embedded.yaml's SEP.APPS.
image-sidecar-embedded: pack
	@podman image exists "sep:${RELEASE_VER}-embedded" && podman image rm "sep:${RELEASE_VER}-embedded" || true
	@buildah build -f sidecar/Containerfile.sidecar --compress --force-rm --squash --no-cache --format docker --memory 100M --isolation rootless --build-arg SEP_RESTRICT_APPS=1 --tag "sep:${RELEASE_VER}-embedded"

format: venv
	@"${VENV_BIN}"/ruff format .
	@"${VENV_BIN}"/djlint . --reformat

ruff: venv
	@"${VENV_BIN}"/ruff check .
	@"${VENV_BIN}"/ruff format --check .

# Opt-in, local-only static type checking (Astral ty). Deliberately NOT part of `lint`,
# pre-commit, or CI: a non-zero exit from the existing type-error backlog is expected and
# must not gate any automated check.
typecheck: venv
	@"${VENV_BIN}"/ty check app

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

# One-time legacy data['_form'] backfill for framework-migrated task apps.
backfill-legacy-forms: venv
	@"${VENV_BIN}"/python -m app.sep.apps.framework.form_backfill $(BACKFILL_ARGS)

pip-audit: venv
	@"${POETRY}" run pip-audit --verbose --progress-spinner=off \
		$$($(PYTHON) -c "import tomllib,pathlib;c=tomllib.loads(pathlib.Path('pyproject.toml').read_text());print(' '.join(f'--ignore-vuln {v}' for v in c.get('tool',{}).get('pip-audit',{}).get('ignore-vulnerabilities',[])))" 2>/dev/null)

bandit: venv
	@"${VENV_BIN}"/bandit -c pyproject.toml -r app

makemigrations: venv alembic.ini app/tasks/models.py app/inventory/models.py app/sep/models.py
	@"${VENV_BIN}"/python scripts/sync_alembic_version_locations.py
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
	@"${VENV_BIN}"/python scripts/sync_alembic_version_locations.py
	@read -p "Enter description for new $(PLUGIN) plugin migration: " desc; \
	"${VENV_BIN}"/alembic --name sep revision --autogenerate --head=$(PLUGIN)@head -m "$$desc"

migrate: venv alembic.ini app/tasks/migrations/versions app/inventory/migrations/versions app/sep/migrations/versions
	@"${VENV_BIN}"/python scripts/sync_alembic_version_locations.py
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
	@$(DARWIN_DYLD) "${VENV_BIN}"/pytest -v -r a -n ${PYTEST_WORKERS} $(if $(filter 1,$(COV)),--cov=app,) $(if ${PYTEST_MARKERS},-m "${PYTEST_MARKERS}",) ${PYTEST_PATHS}

# Regenerate every derived API/form contract from the live app in one pass:
# the route GET /schema + OpenAPI snapshot goldens, the synthetic form-DSL
# goldens, the frontend OpenAPI spec, and the generated TS client. Run after
# changing an app form model, review the diff, then commit.
regen-specs: venv
	@$(DARWIN_DYLD) SEP_UPDATE_SNAPSHOTS=1 "${VENV_BIN}"/pytest -q -p no:cacheprovider tests/app/sep/test_schema_snapshot.py tests/app/sep/test_openapi_snapshot.py tests/app/sep/apps/framework/test_form_dsl_golden.py
	@$(DARWIN_DYLD) "${VENV_BIN}"/python scripts/dump_openapi.py
	@cd frontend && pnpm --filter @sep/api codegen && pnpm --filter @sep/api exec oxfmt --write src/generated

regen-pbm-payloads: venv
	@$(DARWIN_DYLD) "${VENV_BIN}"/python scripts/gen_pbm_payloads.py

regen-pbm-payloads-check: venv
	@$(DARWIN_DYLD) "${VENV_BIN}"/python scripts/gen_pbm_payloads.py --check

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
# TICKET, SECTION and MSG are forwarded through the recipe shell environment as
# "$$VAR" — command-line variables are auto-exported, so the shell (not Make's
# textual expansion) supplies each value and embedded quotes, spaces and backticks
# stay literal (a literal '$' must be written as '$$' on the command line).
# Interpolating "$(MSG)" instead pastes the raw text inside an already-open quoted string, where a `"` closes it and a backtick
# command-substitutes; no caller-side quoting can prevent that.
	@$(PYTHON) scripts/changelog.py add --ticket "$$TICKET" --section "$$SECTION" --message "$$MSG" $(if $(FORCE),--force,)

changelog-check:
	@$(PYTHON) scripts/changelog.py check

changelog-list:
	@$(PYTHON) scripts/changelog.py list

# Bare `make startapp` (no NAME) drops into the interactive wizard. Each value is
# forwarded through the recipe shell environment as "$$VAR" — command-line
# variables are auto-exported, so the shell (not Make's textual expansion) supplies
# the value and embedded spaces/quotes stay intact; a literal `$` must be written
# `$$` on the command line. $(if ...) gates presence. Recognised variables: NAME
# TYPE DISPLAY_NAME DESCRIPTION GROUP SERVICE_TYPE NAV_ICON RUN_MODE COMMAND PAYLOAD
# SCRIPT NO_INPUT ENABLE DERIVE_UPDATE DERIVE_DELETE.
startapp:
	@$(DARWIN_DYLD) "${VENV_BIN}"/python app/sep/apps/framework/scaffold.py \
		$(if $(NAME),--name "$$NAME") \
		$(if $(TYPE),--type "$$TYPE") \
		$(if $(DISPLAY_NAME),--display-name "$$DISPLAY_NAME") \
		$(if $(DESCRIPTION),--description "$$DESCRIPTION") \
		$(if $(GROUP),--group "$$GROUP") \
		$(if $(SERVICE_TYPE),--service-type "$$SERVICE_TYPE") \
		$(if $(NAV_ICON),--nav-icon "$$NAV_ICON") \
		$(if $(RUN_MODE),--run-mode "$$RUN_MODE") \
		$(if $(COMMAND),--command "$$COMMAND") \
		$(if $(PAYLOAD),--payload "$$PAYLOAD") \
		$(if $(SCRIPT),--script "$$SCRIPT") \
		$(if $(NO_INPUT),--no-input) \
		$(if $(ENABLE),--enable) \
		$(if $(filter false 0 no,$(DERIVE_UPDATE)),--no-derive-update) \
		$(if $(filter false 0 no,$(DERIVE_DELETE)),--no-derive-delete)

startapp-check:
	@$(DARWIN_DYLD) "${VENV_BIN}"/python scripts/startapp_check.py

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
	tag='$(value TAG)'; \
	if [ -n "$${JENKINS_URL:-}" ] && [ -n "$${JENKINS_USER:-}" ] && [ -n "$${JENKINS_API_TOKEN:-}" ]; then \
		case "$${tag}" in \
			v*) jenkins_job="Release" ;; \
			*) jenkins_job="Build" ;; \
		esac; \
		echo "==> Triggering Jenkins $${jenkins_job} build for $${tag}..."; \
		if curl -sSf -k -X POST "$${JENKINS_URL}/job/SEP/job/$${jenkins_job}/buildWithParameters" \
			-u "$${JENKINS_USER}:$${JENKINS_API_TOKEN}" \
			--data-urlencode "releaseTag=$${tag}" \
			--data-urlencode "notifySlack=true" \
			--data-urlencode "pushImage=true" \
			--data-urlencode "pushImageDocker=$(PUSH_IMAGE_DOCKER)" 2>&1; then \
			echo "    Jenkins build triggered successfully."; \
			if [ -n "$(WEBHOOK_URL_ENV)" ] && [ -n "$(WEBHOOK_AUTH_ENV)" ]; then \
				$(PYTHON) scripts/post_jira_webhook.py \
					--url-env "$(WEBHOOK_URL_ENV)" \
					--auth-env "$(WEBHOOK_AUTH_ENV)" \
					--version-tag "$${tag}" || true; \
			fi; \
		else \
			echo "    Warning: Failed to trigger Jenkins build. Trigger it manually."; \
		fi; \
	else \
		echo "Note: JENKINS_URL/JENKINS_USER/JENKINS_API_TOKEN not all set, skipping Jenkins trigger."; \
	fi

.PHONY: venv build pack builder image image-sidecar image-sidecar-embedded format ruff typecheck djlint lint audit run-pre-commit dev-backend dev-frontend backfill-legacy-forms pip-audit bandit makemigrations makemigrations-plugin migrate checkmigrations test regen-specs regen-pbm-payloads regen-pbm-payloads-check release-prep release-rc release-stable trigger-jenkins changelog-add changelog-check changelog-list startapp startapp-check
