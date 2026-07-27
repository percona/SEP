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

"""Resolve a plugin callable named by a ``"module:function"`` path, with caching.

Several per-task hooks let the owning plugin *declare* a callable by
``"module:function"`` string on the task and have core resolve it lazily the
first time it is needed — keeping the tasks service free of static ``app.sep``
imports. Those hooks share this resolver so the ``importlib``
resolve-and-cache boilerplate lives in one place.
"""

import importlib
from collections.abc import Callable
from typing import Any

#: Cache of resolved callables, keyed by ``"module:function"`` path.
_RESOLVED: dict[str, Callable[..., Any]] = {}


def resolve_hook(path: str) -> Callable[..., Any]:
    """Import and return the callable named by a ``"module:function"`` path.

    Cache the resolved callable so a repeated lookup for the same path skips the
    import.

    :param path: The callable path in ``"module:function"`` form.
    :return: The resolved callable.
    :raises ImportError: When the named module cannot be imported.
    :raises AttributeError: When the module has no attribute ``function``.
    :raises ValueError: When ``path`` carries no ``:`` separator.
    """
    cached = _RESOLVED.get(path)
    if cached is not None:
        return cached
    module_path, func_name = path.split(":", 1)
    func = getattr(importlib.import_module(module_path), func_name)
    _RESOLVED[path] = func
    return func
