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

"""Share the task names that must never reach an outbound Tasks API path.

Every outbound task path is composed through
:func:`app.extensions.deps.task_path`, so the same names are asserted against that
helper, the dependencies built on it, and the routes that bind them. Keeping
one list here means a newly discovered shape is covered everywhere at once.
"""

PATH_UNSAFE_TASKS = [
    "/evil.example.com:80/x",
    "//evil.example.com/x",
    "../hosts",
    "a/b",
    "x?q=1",
    "x#f",
    "a%2Fb",
    "..",
    "foo:bar",
    "http://evil.example.com/x",
    "a\nb",
    "a\rb",
    "a\tb",
    "a\x0bb",
    "a\x7fb",
    "foo;",
    " foo",
]

PATH_PARAM_UNSAFE_TASKS = [
    task
    for task in PATH_UNSAFE_TASKS
    if "/" not in task and "%" not in task and task != ".."
]
"""The unsafe names that can reach a route through a URL path parameter.

Derived from the list above so a name added there is covered on every route
that binds a task name. Three shapes are excluded because they never reach the
guard rather than because it would admit them: Starlette's default ``str``
convertor is ``[^/]+``, so a name carrying a slash cannot match; a bare
dot-segment is normalised away before the request is sent; and the test
transport unquotes the path twice, so a ``%``-bearing name arrives split across
two segments and matches no route. Those three reach the guard only through a
request body or a stored name, which the dependency-level tests cover.

A name carrying a control character does survive as a path parameter — sent
percent-encoded it arrives decoded — so it stays in this list.
"""

ROUND_TRIP_BASE_PATHS = (
    "http://tasks.example.org",
    "http://tasks.example.org/api/tasks",
)
"""The two ``prepare_path`` branches an accepted name must survive.

A root endpoint hands ``urljoin`` an absolute reference; an endpoint carrying a
path (the ``development`` profile's ``…/api/tasks``, or any sub-path an operator
points PMM Extensions at) strips the leading slash first, so the name reaches ``urljoin`` as
a relative reference and a different set of characters is interpreted there.
"""

SUFFIXED_UNSAFE_TASKS = [task for task in PATH_UNSAFE_TASKS if task != ".."]
"""The unsafe names that stay unsafe once a derived suffix is appended.

A bare dot-segment is the one shape a suffix repairs: ``"..-logical"`` is an
ordinary segment. Tests that compose a sibling name from a parent name assert
against this list so that repair is not mistaken for a missing guard.
"""

SAFE_TASK_NAMES = [
    "backup-task",
    "a.b_c-1",
    "v1.2.3",
    "tasks__sync_running_tasks",
]
"""Legitimate names the guard must keep admitting.

A dot inside a name is ordinary; only a name that *is* a dot-segment resolves to
a different upstream path.
"""
