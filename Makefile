# vim: ts=8:sw=8:ft=make:noai:noet

SHELL=/usr/bin/bash

PYTHON=python3
RELEASE_VER?=
ifdef VIRTUAL_ENV
    VENV=${VIRTUAL_ENV}
else
    VENV?=venv
endif
VENV_BIN?="${VENV}/bin"
PIP?="${VENV_BIN}/pip"
POETRY?="${VENV_BIN}/poetry"


venv: pyproject.toml poetry.lock
	@[[ ! -z "${VIRTUAL_ENV}" || -d "venv" ]] || "${PYTHON}" -m venv "${VENV}"
	@"${PIP}" install --no-cache -U pip wheel poetry;
	@source "${VENV_BIN}"/activate; "${POETRY}" install --with audit

build: venv
	@source "${VENV_BIN}"/activate; "${POETRY}" build --format wheel --output dist

format:
	@"${VENV_BIN}"/ruff format .

lint: venv
	@"${VENV_BIN}"/ruff check .

audit: lint bandit pip-audit

pip-audit: venv
	@"${POETRY}" export -f requirements.txt --output requirements.txt
	@"${VENV_BIN}"/pip-audit --verbose --progress-spinner=off --require-hashes -r requirements.txt; rm requirements.txt

bandit: venv
	@"${VENV_BIN}"/bandit -c pyproject.toml -r app

makemigrations: venv alembic.ini app/tasks/models.py
	@"${VENV_BIN}"/alembic --name tasks check > alembic_check.log 2>&1 || { \
	    if grep -q "Target database is not up to date" alembic_check.log; then \
	        echo "Error: Tasks database is not up to date"; \
	        echo "Error:   Run 'make migrate' to apply the migrations before making new migrations."; \
	        rm alembic_check.log; \
	        exit 1; \
	    elif grep -q "New upgrade operations detected" alembic_check.log; then \
	        echo "New upgrade operations detected. Creating migration."; \
	        "${VENV_BIN}"/alembic --name tasks revision --autogenerate -m "$$(read -p 'Enter description for new Tasks Migration: ' desc && echo $$desc)"; \
	        rm alembic_check.log; \
	        exit 0; \
	    else \
	        cat alembic_check.log; \
	        rm alembic_check.log; \
	        exit 1; \
	    fi \
	}; \
	rm alembic_check.log; \
	echo "No new upgrade operations detected for Tasks"

migrate: venv alembic.ini app/tasks/migrations/versions
	@"${VENV_BIN}"/alembic --name tasks upgrade head