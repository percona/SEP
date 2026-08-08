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

"""Define wire-name constants shared across snippet and framework schema modules."""

from enum import auto, StrEnum

from app.core.utils.fields import EnumFieldMixin


class TextInputHTMLElement(EnumFieldMixin, StrEnum):
    """Enumerate the types of HTML text input elements."""

    INPUT = auto()
    TEXTAREA = auto()


EXTRA_ARGS_FIELD_NAME = "extra_args"
"""Name the synthesized Extra Args execution field on the wire.

Shared, cycle-free home for this spelling: ``app.sep.apps.framework.schema``
and ``app.sep.snippets.models.snippet`` both need it, but ``framework``
imports ``snippet`` (via ``script_helpers.py``), so ``snippet`` can't import
back from ``framework``. This leaf module has no imports of its own, so both
sides can depend on it without cycling.
"""
