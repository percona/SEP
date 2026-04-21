# vim: ts=8:sw=8:ft=make:noai:noet

SHELL=env bash

PYTHON?=python3
RELEASE_VER?=HEAD
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
	START_PKGS=pip wheel poetry
	POETRY="${VENV_BIN}/poetry"
endif
PIP?="${VENV_BIN}/pip"
APPS=tasks inventory sep

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

run-pre-commit: venv
	@"${VENV_BIN}"/pre-commit run --all-files

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
				"${VENV_BIN}"/alembic --name $$app revision --autogenerate -m "$$desc"; \
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

migrate: venv alembic.ini app/tasks/migrations/versions app/inventory/migrations/versions app/sep/migrations/versions
	@for app in $(APPS); do \
		"${VENV_BIN}"/alembic --name $$app upgrade head; \
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
	@"${VENV_BIN}"/pytest -v -r a -n auto --cov=app tests/

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

release-rc:
ifndef VERSION
	$(error VERSION is required. Usage: make release-rc VERSION=X.Y.Z RC=N)
endif
ifndef RC
	$(error RC is required. Usage: make release-rc VERSION=X.Y.Z RC=N)
endif
	@$(PYTHON) scripts/release.py rc --version "$(VERSION)" --rc "$(RC)"

release-stable:
ifndef VERSION
	$(error VERSION is required. Usage: make release-stable VERSION=X.Y.Z)
endif
	@$(PYTHON) scripts/release.py stable --version "$(VERSION)"

trigger-jenkins:
ifndef TAG
	$(error TAG is required. Usage: make trigger-jenkins TAG=vX.Y.Z)
endif
	@set -euo pipefail; \
	if [ -n "$${JENKINS_URL:-}" ] && [ -n "$${JENKINS_USER:-}" ] && [ -n "$${JENKINS_API_TOKEN:-}" ]; then \
		echo "==> Triggering Jenkins release build for $(TAG)..."; \
		if curl -sSf -k -X POST "$${JENKINS_URL}/job/SEP/job/Release/buildWithParameters" \
			-u "$${JENKINS_USER}:$${JENKINS_API_TOKEN}" \
			--data-urlencode "releaseTag=$(TAG)" \
			--data-urlencode "notifySlack=true" \
			--data-urlencode "pushImage=true" \
			--data-urlencode "pushImageDocker=true" 2>&1; then \
			echo "    Jenkins build triggered successfully."; \
		else \
			echo "    Warning: Failed to trigger Jenkins build. Trigger it manually."; \
		fi; \
	else \
		echo "Note: JENKINS_URL/JENKINS_USER/JENKINS_API_TOKEN not all set, skipping Jenkins trigger."; \
	fi

.PHONY: venv build pack builder image format ruff djlint lint audit run-pre-commit pip-audit bandit makemigrations migrate checkmigrations test release-rc release-stable trigger-jenkins changelog-add changelog-check changelog-list
