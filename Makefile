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
APPS=tasks inventory sep


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

makemigrations: venv alembic.ini app/tasks/models.py app/inventory/models.py
	@for app in $(APPS); do \
		capitalized=$${app^}; \
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

compile-css: venv
	@source "${VENV_BIN}"/activate; "${PYTHON}" compile_scss.py