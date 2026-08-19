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

"""Name the execution fields a script app's form can synthesize.

Together these are the union of what the script apps append to a script's
frontmatter parameters when building an execution form; each app synthesizes
its own subset, and some of those are conditional on the script's configuration.
A consumer that merges or strips them needs the same spelling the producer used,
whichever app produced them. :data:`RESERVED_EXECUTION_FIELD_NAMES` closes the loop
back at the other producer of form fields, the script author: a frontmatter
parameter declaring one of these names is rejected where frontmatter parameters
are parsed, so a synthesized field can never collide with an author-declared one.

Lives alongside (not inside) :mod:`app.sep.apps.framework` because both ends of an
existing one-way dependency need these spellings:
:mod:`app.sep.apps.framework.script_helpers` imports
:mod:`app.sep.snippets.models.snippet`, so nothing under ``app.sep.snippets.models``
can import back from ``framework``. This module imports nothing, so the form
builders under ``framework`` and the parameter model under ``snippets.models`` can
both depend on it without closing that loop.
"""

#: Name the synthesized execution-host field on the wire.
EXECUTOR_HOST_FIELD_NAME = "executor_host"

#: Name the synthesized sudo toggle on the wire.
SUDO_FIELD_NAME = "sudo"

#: Name the synthesized script-preview field on the wire.
SCRIPT_PREVIEW_FIELD_NAME = "script_preview"

#: Name the synthesized Extra Args field on the wire.
EXTRA_ARGS_FIELD_NAME = "extra_args"

RESERVED_EXECUTION_FIELD_NAMES = frozenset(
    {
        EXECUTOR_HOST_FIELD_NAME,
        SUDO_FIELD_NAME,
        SCRIPT_PREVIEW_FIELD_NAME,
        EXTRA_ARGS_FIELD_NAME,
    }
)
"""Reserve every synthesized field name against frontmatter parameter names.

Reservation is unconditional and app-wide: a name is reserved even for a script
whose app never synthesizes that particular field (a ``sudo: never`` snippet, a
disk-backed script app with no preview endpoint), because the alternative is a
per-app, per-configuration rule that the author of a frontmatter file cannot
evaluate from the file in front of them.

The members are the same constants the form builders synthesize from, so reserving
a fifth name is a two-line edit in this module and cannot be forgotten at the
validator.
"""
