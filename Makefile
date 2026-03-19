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
	@"${POETRY}" run pip-audit --verbose --progress-spinner=off

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
	@"${VENV_BIN}"/pytest -v -r a --cov=app tests/

release-rc:
ifndef VERSION
	$(error VERSION is required. Usage: make release-rc VERSION=X.Y.Z RC=N)
endif
ifndef RC
	$(error RC is required. Usage: make release-rc VERSION=X.Y.Z RC=N)
endif
	@CURRENT_BRANCH=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$(RC)" = "1" ] && [ "$$CURRENT_BRANCH" != "main" ]; then \
		echo "Error: RC=1 requires being on the main branch (currently on $$CURRENT_BRANCH)"; \
		exit 1; \
	fi; \
	if [ -n "$$(git status --porcelain)" ]; then \
		echo "Error: Working tree is not clean. Commit or stash changes first."; \
		exit 1; \
	fi; \
	RC_VERSION="$(VERSION)rc$(RC)"; \
	BRANCH="release/v$(VERSION)"; \
	if [ "$(RC)" = "1" ]; then \
		echo "==> Pulling latest main..."; \
		git pull origin main; \
		echo "==> Creating release branch $$BRANCH..."; \
		git checkout -b "$$BRANCH"; \
	else \
		echo "==> Checking out existing release branch $$BRANCH..."; \
		git checkout "$$BRANCH"; \
		git pull origin "$$BRANCH"; \
	fi; \
	echo "==> Bumping version to $$RC_VERSION..."; \
	sed -i "s/^version = .*/version = \"$$RC_VERSION\"/" pyproject.toml; \
	sed -i "s/^__version__ = .*/__version__ = \"v$$RC_VERSION\"/" app/__init__.py; \
	echo "==> Committing version bump..."; \
	git commit -am "Bump version to v$$RC_VERSION"; \
	echo "==> Tagging v$$RC_VERSION..."; \
	git tag "v$$RC_VERSION"; \
	echo "==> Pushing branch and tag..."; \
	git push origin "$$BRANCH" "v$$RC_VERSION"; \
	if command -v gh > /dev/null 2>&1; then \
		echo "==> Creating GitHub pre-release..."; \
		gh release create "v$$RC_VERSION" --prerelease --generate-notes --target "$$BRANCH"; \
	else \
		echo "Note: gh CLI not found, skipping GitHub release creation."; \
	fi; \
	echo ""; \
	echo "=== RC $$RC_VERSION released successfully ==="; \
	echo ""; \
	echo "Next steps:"; \
	echo "  1. Create Jira version $(VERSION) (if not already created)"; \
	echo "  2. Trigger Jenkins RC build for v$$RC_VERSION"; \
	echo "  3. Deploy to staging and verify"; \
	echo "  4. Notify the team"

release-stable:
ifndef VERSION
	$(error VERSION is required. Usage: make release-stable VERSION=X.Y.Z)
endif
	@CURRENT_BRANCH=$$(git rev-parse --abbrev-ref HEAD); \
	EXPECTED_BRANCH="release/v$(VERSION)"; \
	if [ "$$CURRENT_BRANCH" != "$$EXPECTED_BRANCH" ]; then \
		echo "Error: Must be on $$EXPECTED_BRANCH (currently on $$CURRENT_BRANCH)"; \
		exit 1; \
	fi; \
	if [ -n "$$(git status --porcelain)" ]; then \
		echo "Error: Working tree is not clean. Commit or stash changes first."; \
		exit 1; \
	fi; \
	echo "==> Bumping version to $(VERSION)..."; \
	sed -i "s/^version = .*/version = \"$(VERSION)\"/" pyproject.toml; \
	sed -i "s/^__version__ = .*/__version__ = \"v$(VERSION)\"/" app/__init__.py; \
	echo "==> Committing version bump..."; \
	git commit -am "Bump version to v$(VERSION)"; \
	echo "==> Tagging v$(VERSION)..."; \
	git tag "v$(VERSION)"; \
	echo "==> Pushing branch and tag..."; \
	git push origin "$$EXPECTED_BRANCH" "v$(VERSION)"; \
	echo "==> Building wheel..."; \
	$(MAKE) build; \
	WHEEL="dist/sep-$(VERSION)-py3-none-any.whl"; \
	if command -v gh > /dev/null 2>&1; then \
		echo "==> Creating GitHub release..."; \
		gh release create "v$(VERSION)" --generate-notes; \
		if [ -f "$$WHEEL" ]; then \
			gh release upload "v$(VERSION)" "$$WHEEL"; \
		else \
			echo "Warning: Wheel not found at $$WHEEL, skipping upload."; \
		fi; \
	else \
		echo "Note: gh CLI not found, skipping GitHub release creation."; \
	fi; \
	echo "==> Creating dev version bump PR on main..."; \
	MINOR=$$(echo "$(VERSION)" | cut -d. -f2); \
	NEXT_MINOR=$$((MINOR + 1)); \
	PREFIX=$$(echo "$(VERSION)" | cut -d. -f1); \
	DEV_VERSION="$$PREFIX.$$NEXT_MINOR.0.dev0"; \
	DEV_BRANCH="bump-dev-version-$$DEV_VERSION"; \
	git fetch origin main; \
	git checkout -b "$$DEV_BRANCH" origin/main; \
	sed -i "s/^version = .*/version = \"$$DEV_VERSION\"/" pyproject.toml; \
	sed -i "s/^__version__ = .*/__version__ = \"v$$DEV_VERSION\"/" app/__init__.py; \
	git commit -am "Bump version to v$$DEV_VERSION"; \
	git push -u origin "$$DEV_BRANCH"; \
	if command -v gh > /dev/null 2>&1; then \
		gh pr create --base main --title "Bump dev version to v$$DEV_VERSION" \
			--body "Automated dev version bump after v$(VERSION) stable release."; \
	else \
		echo "Note: gh CLI not found. Manually create a PR from $$DEV_BRANCH to main."; \
	fi; \
	echo "==> Deleting release branch..."; \
	git checkout main; \
	git push origin --delete "$$EXPECTED_BRANCH" || true; \
	git branch -d "$$EXPECTED_BRANCH" || true; \
	echo ""; \
	echo "=== Stable $(VERSION) released successfully ==="; \
	echo ""; \
	echo "Next steps:"; \
	echo "  1. Trigger Jenkins stable build for v$(VERSION)"; \
	echo "  2. Publish release notes"; \
	echo "  3. Mark Jira version $(VERSION) as released"; \
	echo "  4. Merge the dev version bump PR"

.PHONY: venv build pack builder image format ruff djlint lint audit run-pre-commit pip-audit bandit makemigrations migrate checkmigrations test release-rc release-stable
