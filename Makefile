# vim: ts=8:sw=8:ft=make:noai:noet

SHELL=/usr/bin/bash

PYTHON=python3.11
RELEASE_VER?=
VENV?=venv
PIP="${VENV}/bin/pip"


prep:
	@install -d build/tmp

venv: prep
	@"${PYTHON}" -m venv "${VENV}"
	@"${VENV}"/bin/pip install --no-cache -U pip wheel;
	@[[ ! -f requirements.txt ]] || "${VENV}"/bin/pip install --no-cache -r requirements.txt;

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
	@pip install --upgrade --quiet bandit
	@bandit -c pyproject.toml -r src
