# vim: ts=8:sw=8:ft=make:noai:noet

SHELL?=/usr/bin/bash

PYTHON=python3.11
RELEASE_VER?=
ifdef VIRTUAL_ENV
    VENV=${VIRTUAL_ENV}
else
    VENV?=venv
endif
VENV_BIN="${VENV}/bin"
PIP="${VENV_BIN}/pip"


prep:
	@install -d build/tmp

venv: prep
	@[[ ! -z "${VIRTUAL_ENV}" || -d "venv" ]] || "${PYTHON}" -m venv "${VENV}"
	@"${PIP}" install --no-cache -U pip wheel poetry;
	@source "${VENV_BIN}"/activate; "${VENV_BIN}"/poetry install

build: export TMPDIR=build/tmp
build: prep
	@python3 -m build --wheel --outdir build
	@rm -rf sep.egg-info

format:
	@ruff format .

lint:
	@pip install --upgrade ruff
	@ruff check .

audit: export TMPDIR=build/tmp
audit: prep lint bandit pip-audit

pip-audit:
	@pip install --upgrade --quiet pip-tools pip-audit
	@pip-compile --no-strip-extras --generate-hashes pyproject.toml
	@pip-audit --verbose --progress-spinner=off --require-hashes -r requirements.txt

bandit:
	@pip install --upgrade --quiet bandit toml 'bandit[toml]'
	@bandit -c pyproject.toml -r src

css:
	@sassc src/sass/css/base.scss static/themes/materialize/css/base.css
