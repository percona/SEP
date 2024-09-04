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
