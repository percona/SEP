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

"""Guard every app package against an import-time break.

Six app packages used to re-export the Jinja router from their ``__init__.py``
(``from app.sep.apps.<app>.routes import router``). Deleting ``routes.py``
without editing those re-exports raises ``ModuleNotFoundError`` at *package
import* — before the registry is built — so the failure surfaces as a total
startup crash rather than a missing route. Importing every package here catches
that class of break directly, independent of whichever apps a given activation
list happens to mount.
"""

import importlib
import pkgutil

import pytest

import app.sep.apps as apps_package

#: Every app subpackage on disk, discovered rather than listed, so an app added
#: later is covered without editing this module.
APP_PACKAGE_NAMES = sorted(
    module.name
    for module in pkgutil.iter_modules(apps_package.__path__)
    if module.ispkg and module.name not in {"framework", "shared"}
)


def test_app_packages_discovered() -> None:
    """Assert discovery found the app packages, so the sweep is not vacuous."""
    expected_minimum = 15
    assert len(APP_PACKAGE_NAMES) >= expected_minimum


@pytest.mark.parametrize("package_name", APP_PACKAGE_NAMES)
def test_app_package_imports(package_name: str) -> None:
    """Assert the app package imports cleanly."""
    assert importlib.import_module(f"app.sep.apps.{package_name}") is not None


@pytest.mark.parametrize("package_name", APP_PACKAGE_NAMES)
def test_app_package_exports_no_jinja_router(package_name: str) -> None:
    """Assert no package still re-exports a ``router`` from the deleted Jinja layer."""
    package = importlib.import_module(f"app.sep.apps.{package_name}")

    assert not hasattr(package, "router")
    assert "router" not in getattr(package, "__all__", ())
