# vim: ts=8:sw=8:ft=make:noai:noet

SHELL?=`which bash`

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
	@[[ ! -z "${VIRTUAL_ENV}" || -d "venv" ]] || "${PYTHON}" -m venv "${VENV}"
	@"${PIP}" install --no-cache ${START_PKGS};
	@source "${VENV_BIN}"/activate; "${POETRY}" install --with audit

build: venv app/
	@source "${VENV_BIN}"/activate; "${POETRY}" build --format wheel --output dist

pack:
ifndef BUNDLE
	@echo Exporting bundle
	@git archive --output=bundle.tgz --format=tar.gz "${RELEASE_VER}" app static templates
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

audit: run-pre-commit bandit pip-audit

run-pre-commit: venv
	@"${VENV_BIN}"/pre-commit run --all-files

pip-audit: venv
	@"${POETRY}" export -f requirements.txt --output requirements.txt
	@${VENV_BIN}/pip-audit --verbose --progress-spinner=off --disable-pip --require-hashes -r requirements.txt; status=$$?; rm requirements.txt; exit $$status

bandit: venv
	@"${VENV_BIN}"/bandit -c pyproject.toml -r app

makemigrations: venv alembic.ini app/tasks/models.py app/inventory/models.py
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

migrate: venv alembic.ini app/tasks/migrations/versions
	@for app in $(APPS); do \
		"${VENV_BIN}"/alembic --name $$app upgrade head; \
	done

test: venv
	@"${VENV_BIN}"/pytest -v -r a --cov=app tests/
