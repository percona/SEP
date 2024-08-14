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

lint: venv
	@"${PIP}" install --upgrade ruff
	@ruff check .

audit: export TMPDIR=build/tmp
audit: prep lint bandit pip-audit

pip-audit: venv
	@"${PIP}" install --upgrade --quiet pip-tools pip-audit
	@"${VENV_BIN}"/pip-compile --no-strip-extras --generate-hashes pyproject.toml
	@"${VENV_BIN}"/pip-audit --verbose --progress-spinner=off --require-hashes -r requirements.txt
	@rm requirements.txt

bandit: venv
	@"${PIP}" install --upgrade --quiet bandit[toml]
	@"${VENV_BIN}"/bandit -c pyproject.toml -r src

css:
	@sassc src/sass/css/base.scss static/themes/materialize/css/base.css
