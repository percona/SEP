#!/usr/bin/env python3
# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Dump the four whole-app OpenAPI specs the frontend codegen consumes.

Writes canonical JSON for the ``main``, ``inventory``, ``tasks``, and ``sep``
apps to ``frontend/packages/api/specs/``. The top-level ``main`` spec is the
core API only (``app.openapi()``), not the merged ``/api/openapi.json`` document.

Run this outside pytest: sibling conftests inject routers into the process-global
``sep_app`` at import time, so a spec computed inside the test process would
depend on test-collection order.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import fastapi.openapi.utils

REPO_ROOT = Path(__file__).resolve().parents[1]
SPECS_DIR = REPO_ROOT / "frontend" / "packages" / "api" / "specs"


def canonical(doc: dict[str, Any]) -> str:
    """Return deterministic JSON for ``doc``: sorted keys, 2-space indent, trailing newline.

    ``sort_keys`` neutralizes dict-key-order nondeterminism so the rendered bytes
    are stable across runs and Python versions, matching the byte format the
    backend snapshot tests use.

    :param doc: The OpenAPI document to render.
    :return: Canonical UTF-8 JSON text with a single trailing newline.
    """
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


_ORIGINAL_GET_MODEL_NAME_MAP = fastapi.openapi.utils.get_model_name_map


def _ordered_model_name_map(unique_models: set[Any]) -> dict[Any, str]:
    """Build FastAPI's schema-name map from models sorted by qualified name.

    ``get_model_name_map`` iterates a ``set`` of model classes, so when a model
    ``__name__`` collides across plugins (for example ``BackupTaskWrite`` exists
    in both the backup_mongo and backup_pg plugins) the model that wins the short
    schema name versus a module-qualified one depends on per-process object
    ordering. Sorting by qualified name first makes the generated spec
    reproducible, which the freshness guard relies on.

    :param unique_models: The model classes FastAPI collected for the spec.
    :return: The model-to-name mapping with deterministic collision names.
    """
    return _ORIGINAL_GET_MODEL_NAME_MAP(
        sorted(unique_models, key=lambda model: (model.__module__, model.__qualname__))
    )


def _patch_deterministic_schema_names() -> None:
    """Ensure FastAPI's schema-name resolution is deterministic across processes."""
    fastapi.openapi.utils.get_model_name_map = _ordered_model_name_map


# The same pins `[tool.pytest.ini_options].env` applies in ``pyproject.toml``,
# so a dump and the freshness guard resolve identical settings. Keep both sites
# in sync.
_CANONICAL_ENV = {
    "ENV_FILE": str(REPO_ROOT / "tests" / "pytest.env"),
    "AUTH__PROVIDER__CASDOOR__CLIENT_ID": "test-client-id",
    "AUTH__PROVIDER__CASDOOR__CLIENT_SECRET": "test-client-secret",
    "AUTH__PROVIDER__CASDOOR__ALLOWED_ISSUERS": '["https://allowed-issuer.com"]',
}


def _pin_canonical_settings_env() -> None:
    """Pin the settings environment so the generated spec is environment-independent.

    The spec is a build artifact whose shape must not vary with the developer's
    local configuration, so both settings sources able to name an auth provider
    are neutralized:

    - ``ENV_FILE`` is repointed at the committed assignment-free dotenv, since
      it selects the file the dotenv source reads. Exporting variables cannot
      dislodge a provider that a developer's ``ENV_FILE=.env.local`` supplies,
      because the dotenv source reads that file from disk regardless.
    - Pre-existing ``AUTH__PROVIDER*`` variables are cleared, so an exported
      provider cannot survive alongside the canonical one.

    Leaving either source in place resolves a second provider, which
    ``AuthSettings`` rejects outright rather than merging.

    Must be called before ``_load_apps()`` imports the application, since the
    settings object is constructed at import time.
    """
    for key in [k for k in os.environ if k.startswith("AUTH__PROVIDER")]:
        del os.environ[key]
    for key, value in _CANONICAL_ENV.items():
        os.environ[key] = value


def _load_apps() -> dict[str, Any]:
    """Import the whole-app objects from the worktree this script lives in.

    The shared virtualenv carries an editable ``.pth`` that appends one fixed
    worktree to ``sys.path``. Executing a script puts its own ``scripts/``
    directory on ``sys.path`` but not the repo root, so a bare ``import app``
    would resolve to that ``.pth`` worktree rather than the tree whose specs this
    script writes. Prepending ``REPO_ROOT`` binds the dump to the local worktree.

    :return: The four whole-app objects keyed by spec name.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from app.inventory.main import inventory_app
    from app.main import app as main_app
    from app.sep.main import sep_app
    from app.tasks.main import tasks_app

    return {
        "main": main_app,
        "inventory": inventory_app,
        "tasks": tasks_app,
        "sep": sep_app,
    }


def main() -> int:
    """Write or check the committed spec fixtures.

    :return: ``0`` when every fixture is fresh (or written); ``1`` when ``--check``
        finds a missing or drifted fixture.
    """
    _patch_deterministic_schema_names()
    _pin_canonical_settings_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the committed fixtures against a fresh dump without writing",
    )
    args = parser.parse_args()
    apps = _load_apps()
    # Imported after _load_apps() prepends REPO_ROOT to sys.path so the local
    # worktree's app package is resolved, not the editable .pth worktree.
    from app.core.utils.openapi import namespaced_openapi

    drift = []
    for name, fastapi_app in apps.items():
        content = canonical(namespaced_openapi(fastapi_app))
        target = SPECS_DIR / f"{name}.json"
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                drift.append(name)
        else:
            SPECS_DIR.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    if drift:
        print(
            f"OpenAPI spec drift: {drift}; regenerate with `python scripts/dump_openapi.py`",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
