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

"""Test the per-script Dipper execution form schema."""

from typing import Any

import pytest

from app.sep.apps.dipper.schema import build_dipper_form_schema
from app.sep.apps.field_names import (
    EXECUTOR_HOST_FIELD_NAME,
    RESERVED_EXECUTION_FIELD_NAMES,
    SCRIPT_PREVIEW_FIELD_NAME,
    SUDO_FIELD_NAME,
)
from app.sep.apps.framework.schema import BoolField, HostField, ScriptPreviewField
from app.sep.snippets.config import SnippetSudoOption
from app.sep.snippets.models.snippet import BaseSnippet
from tests.app.sep.form_schema_utils import form_field_names, form_field_types

SERVICE_ID = 1
COLLECTOR_TYPE = "environment"

#: The execution fields this builder synthesizes, and the widget rendering each.
SYNTHESIZED_FIELD_TYPES = {
    EXECUTOR_HOST_FIELD_NAME: HostField,
    SUDO_FIELD_NAME: BoolField,
    SCRIPT_PREVIEW_FIELD_NAME: ScriptPreviewField,
}


def _script(**meta: Any) -> BaseSnippet:
    """Return a DB-free script carrying the given frontmatter meta."""
    return BaseSnippet(
        filename="collect.py",
        size=1,
        md5_digest="a" * 32,
        meta={
            "title": "Collect",
            "sudo": SnippetSudoOption.OPTIONAL.value,
            **meta,
        },
    )


class TestReservedParameterNames:
    """Cover frontmatter parameters colliding with synthesized execution fields."""

    @pytest.mark.parametrize("reserved_name", sorted(RESERVED_EXECUTION_FIELD_NAMES))
    def test_reserved_named_parameter_is_dropped_not_raised(
        self, reserved_name: str
    ) -> None:
        """Drop a reserved-name parameter instead of failing the schema build.

        Reservation is unconditional, so this also holds for ``extra_args``,
        which Dipper never synthesizes.

        Asserting the whole field set, rather than only that the reserved name
        appears at most once, keeps a build that dropped the *synthesized* field
        as well from passing; asserting its type keeps one silently retyped from
        passing either.
        """
        script = _script(parameters=[{"name": reserved_name, "type": "str"}])

        schema = build_dipper_form_schema(
            script, service_id=SERVICE_ID, collector_type=COLLECTOR_TYPE
        )

        assert not any(section.title == "Parameters" for section in schema.forms)
        assert form_field_names(schema) == sorted(SYNTHESIZED_FIELD_TYPES)
        assert form_field_types(schema) == SYNTHESIZED_FIELD_TYPES

    def test_every_synthesized_field_name_is_reserved(self) -> None:
        """Keep every field this builder synthesizes covered by the reserved set."""
        schema = build_dipper_form_schema(
            _script(), service_id=SERVICE_ID, collector_type=COLLECTOR_TYPE
        )

        assert form_field_types(schema) == SYNTHESIZED_FIELD_TYPES
        assert set(form_field_names(schema)) <= RESERVED_EXECUTION_FIELD_NAMES
