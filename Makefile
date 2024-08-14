# vim: ts=8:sw=8:ft=make:noai:noet

SHELL?=/usr/bin/bash

PYTHON=python3
RELEASE_VER?=
ifdef VIRTUAL_ENV
    VENV=${VIRTUAL_ENV}
else
    VENV?=venv
endif
VENV_BIN="${VENV}/bin"
PIP="${VENV_BIN}/pip"
POETRY="${VENV_BIN}/poetry"


venv: pyproject.toml poetry.lock
	@[[ ! -z "${VIRTUAL_ENV}" || -d "venv" ]] || "${PYTHON}" -m venv "${VENV}"
	@"${PIP}" install --no-cache -U pip wheel poetry;
	@source "${VENV_BIN}"/activate; "${POETRY}" install --with audit

build: venv
	@source "${VENV_BIN}"/activate; "${POETRY}" build --format wheel --output dist

format:
	@ruff format .

lint: venv
	@"${VENV_BIN}"/ruff check .

audit: prep lint bandit pip-audit

pip-audit: venv
	@"${VENV_BIN}"/pip-compile --no-strip-extras --generate-hashes pyproject.toml
	@"${VENV_BIN}"/pip-audit --verbose --progress-spinner=off --require-hashes -r requirements.txt
	@rm requirements.txt

bandit: venv
	@"${VENV_BIN}"/bandit -c pyproject.toml -r src

css:
	@sassc src/sass/css/base.scss static/themes/materialize/css/base.css
