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

"""Pin the import boundary of the relocated snippet response models."""

import ast
from pathlib import Path

import pytest

import app.sep.snippets.models as snippets_models

PACKAGE_INIT = Path(snippets_models.__file__)


class TestModelsPackageImportBoundary:
    """Keep ``responses`` out of the models package root.

    ``app/sep/migrations/env.py`` star-imports this package and ``crud.py``
    imports it, so a root-level re-export would drag
    ``app.sep.apps.framework.schema`` -- and through it ``app.inventory.models``
    -- into Alembic's migration environment. It would also close a
    framework/library module cycle that only stays open because
    ``framework/schema.py`` does not import ``framework/script_helpers.py``.
    """

    def test_package_root_does_not_reexport_responses(self):
        """Assert consumers import ``models.responses`` explicitly."""
        assert not hasattr(snippets_models, "SnippetResponse")

    @pytest.mark.parametrize(
        "symbol", ["SnippetResponse", "build_snippet_response", "responses"]
    )
    def test_package_init_names_no_response_symbol(self, symbol):
        """Assert no import statement in ``__init__`` reaches the responses module."""
        tree = ast.parse(PACKAGE_INIT.read_text(encoding="utf-8"))
        imported = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom | ast.Import)
            for alias in node.names
        }
        assert symbol not in imported

    def test_package_root_pulls_no_apps_framework_module(self):
        """Assert importing the package leaves the apps framework out of its namespace."""
        offenders = [
            name
            for name, value in vars(snippets_models).items()
            if getattr(value, "__module__", "").startswith("app.sep.apps.framework")
        ]
        assert not offenders
