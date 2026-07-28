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

"""Define tests for the shared ``app.tasks.hook_resolver`` colon-path resolver."""

import importlib

import pytest

from app.tasks import alert_hooks, hook_resolver
from app.tasks.hook_resolver import resolve_hook


@pytest.fixture(autouse=True)
def _clear_cache(mocker):
    """Reset the resolver cache before each test."""
    mocker.patch.dict(hook_resolver._RESOLVED, {}, clear=True)


def test_resolves_module_function_path():
    """Return the callable named by a ``"module:function"`` path."""
    resolved = resolve_hook("app.tasks.alert_hooks:build_owner_alert_details")
    assert resolved is alert_hooks.build_owner_alert_details


def test_caches_resolved_callable(mocker):
    """Serve a repeated path from cache without re-importing the module."""
    spy = mocker.spy(importlib, "import_module")
    path = "app.tasks.alert_hooks:build_owner_alert_details"

    first = resolve_hook(path)
    second = resolve_hook(path)

    assert first is second
    spy.assert_called_once_with("app.tasks.alert_hooks")


def test_raises_import_error_for_unknown_module():
    """Raise ``ImportError`` when the module cannot be imported."""
    with pytest.raises(ImportError):
        resolve_hook("app.tasks.no_such_module:thing")


def test_raises_attribute_error_for_unknown_attribute():
    """Raise ``AttributeError`` when the module has no such attribute."""
    with pytest.raises(AttributeError):
        resolve_hook("app.tasks.alert_hooks:does_not_exist")


def test_raises_value_error_for_pathless_string():
    """Raise ``ValueError`` when the path carries no ``:`` separator."""
    with pytest.raises(ValueError, match="unpack"):
        resolve_hook("no_colon_here")
