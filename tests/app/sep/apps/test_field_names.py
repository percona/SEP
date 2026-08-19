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

"""Test the synthesized execution field-name vocabulary."""

import ast
from pathlib import Path

from app.sep.apps import field_names
from app.sep.apps.atw.batch import _SYNTHETIC_FIELD_NAMES, NON_SHAREABLE_FIELD_NAMES
from app.sep.apps.field_names import (
    EXECUTOR_HOST_FIELD_NAME,
    EXTRA_ARGS_FIELD_NAME,
    RESERVED_EXECUTION_FIELD_NAMES,
    SCRIPT_PREVIEW_FIELD_NAME,
    SUDO_FIELD_NAME,
)


class TestWireNames:
    """Test the spelling of each synthesized execution field name."""

    def test_each_constant_spells_its_wire_name(self) -> None:
        """Pin the wire spelling of every synthesized execution field."""
        assert EXECUTOR_HOST_FIELD_NAME == "executor_host"
        assert SUDO_FIELD_NAME == "sudo"
        assert SCRIPT_PREVIEW_FIELD_NAME == "script_preview"
        assert EXTRA_ARGS_FIELD_NAME == "extra_args"


class TestReservedExecutionFieldNames:
    """Test the set reserved against frontmatter parameter names."""

    def test_reserves_every_field_name_the_module_declares(self) -> None:
        """Reserve every wire name declared here, and nothing else.

        The expectation is read off the module's own constants rather than
        retyped, so a fifth constant added without being added to the frozenset
        fails here, which is the whole point of a single definition site. A
        retyped expectation would stay green in exactly that case; the wire
        spellings are pinned once, in :class:`TestWireNames`.
        """
        declared = {
            value
            for name, value in vars(field_names).items()
            if name.endswith("_FIELD_NAME")
        }

        assert declared == RESERVED_EXECUTION_FIELD_NAMES

    def test_reserves_exactly_what_the_batch_merge_splits(self) -> None:
        """Pin ATW's hand-maintained split of these names against the set itself.

        ``atw.batch`` keeps its own two frozensets, one for the fields it strips
        because the caller re-synthesizes them and one for the fields it refuses to
        promote to a batch's shared section, and merges a batch form off those
        rather than off this module. A fifth name added here would be reserved
        against frontmatter for free while ATW's merge still treated it as an
        ordinary shareable parameter, so their union is pinned rather than assumed.
        """
        assert (
            _SYNTHETIC_FIELD_NAMES | NON_SHAREABLE_FIELD_NAMES
            == RESERVED_EXECUTION_FIELD_NAMES
        )

    def test_is_immutable(self) -> None:
        """Keep the reserved set immutable so no consumer can widen it in place."""
        assert isinstance(RESERVED_EXECUTION_FIELD_NAMES, frozenset)


class TestLeafModule:
    """Test that the vocabulary module stays importable from both directions."""

    def test_declares_no_runtime_imports(self) -> None:
        """Keep the module import-free so it can never close an import cycle.

        ``app.sep.apps.framework`` and ``app.sep.snippets.models`` both depend
        on these names, and ``framework.script_helpers`` already imports
        ``snippets.models.snippet``. An import added here would close that loop,
        so the absence of imports is the module's whole contract. ``__future__``
        is exempt: it binds no module and so cannot cycle.
        """
        source = Path(field_names.__file__).read_text()
        imported = [
            alias.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Import | ast.ImportFrom)
            for alias in node.names
            if getattr(node, "module", None) != "__future__"
        ]
        assert imported == []
