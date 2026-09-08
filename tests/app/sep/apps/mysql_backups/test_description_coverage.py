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

"""Exercise the description-coverage helpers against models the real apps cannot show.

The two MySQL Backups contract suites only ever call these helpers with fully
described models, so every failure branch is unexercised there. These cases pin
the branches that decide *which* fields the helpers consider theirs to check —
the part a later edit could silently narrow.
"""

from typing import Annotated, Any

import pytest

from app.sep.apps.framework.form_dsl import TaskFormModel, Ui
from tests.app.sep.apps.mysql_backups.description_coverage import (
    assert_every_declared_field_is_described,
    assert_schema_serves_only_declared_descriptions,
)


class _RedeclaresInheritedField(TaskFormModel):
    """Re-declare an inherited Task field to carry its own presentation metadata."""

    task_name: Annotated[str, Ui(label="Job name", section="Task")]


class _DeclaresViaMixin(_RedeclaresInheritedField):
    """Inherit a locally declared field from an intermediate base, declaring none."""


class _DescribesOneField(TaskFormModel):
    """Declare a single described field, so the served-schema checks have a subject."""

    retries: Annotated[
        int, Ui(label="Retries", section="General", description="How many")
    ]


class _DeclaresNothing(TaskFormModel):
    """Declare no fields at all, leaving the helpers with nothing to inspect."""


class _NamesACliFlag(TaskFormModel):
    """Describe a field by the flag it becomes rather than by its effect."""

    retries: Annotated[
        int,
        Ui(
            label="Retries",
            section="General",
            description="Passes --safe-slave-backup so the replica pauses",
        ),
    ]


class _CarriesRstMarkup(TaskFormModel):
    """Describe a field with rST inline code the renderer emits verbatim."""

    retries: Annotated[
        int,
        Ui(label="Retries", section="General", description="Either ``daily`` or none"),
    ]


class _DescribesWithWhitespace(TaskFormModel):
    """Carry a description the wire schema accepts but an operator cannot read."""

    retries: Annotated[int, Ui(label="Retries", section="General", description="   ")]


def _schema_payload(*fields: dict[str, Any]) -> dict[str, Any]:
    """Return a minimal ``GET /schema`` body carrying the given field entries.

    :param fields: The field entries to serve, in order, under one form section.
    :return: A schema payload shaped like the real endpoint's response.
    """
    return {"forms": [{"title": "General", "fields": list(fields)}]}


class TestDeclaredFieldSelection:
    """Assert which fields the coverage helper treats as the model's own."""

    def test_redeclared_inherited_field_is_still_checked(self) -> None:
        """Require helper text on a field the model re-declares under an inherited name.

        Re-declaring an inherited field is how a model takes over its
        presentation, so the field becomes the model's to describe. Excluding it
        by name would let it ship as bare label and widget.
        """
        with pytest.raises(AssertionError, match=r"no description: \['task_name'\]"):
            assert_every_declared_field_is_described(_RedeclaresInheritedField)

    def test_field_inherited_from_an_intermediate_base_is_still_checked(self) -> None:
        """Require helper text on a field an intermediate base declares.

        Splitting fields across mixins must not exempt them: the leaf model's own
        annotations are a narrower set than the fields it actually serves.
        """
        with pytest.raises(AssertionError, match=r"no description: \['task_name'\]"):
            assert_every_declared_field_is_described(_DeclaresViaMixin)


class TestServedSchemaFidelity:
    """Assert the served-schema half of the promise rejects an unreadable payload."""

    def test_a_field_served_twice_fails_fast(self) -> None:
        """Reject a schema serving one field name twice, whatever the texts are.

        Comparing a name-keyed mapping lets a later duplicate win silently, so a
        wrong description would pass whenever a correct one followed it.
        """
        payload = _schema_payload(
            {"name": "retries", "description": "Something else entirely"},
            {"name": "retries", "description": "How many"},
        )

        with pytest.raises(
            AssertionError, match=r"served more than once: \['retries'\]"
        ):
            assert_schema_serves_only_declared_descriptions(payload, _DescribesOneField)

    def test_a_field_served_once_is_compared_on_its_text(self) -> None:
        """Compare the served text against the marker text when the name is unique."""
        payload = _schema_payload(
            {"name": "retries", "description": "Something else entirely"}
        )

        with pytest.raises(
            AssertionError, match=r"not served on the wire: \['retries'\]"
        ):
            assert_schema_serves_only_declared_descriptions(payload, _DescribesOneField)


class TestDescriptionQuality:
    """Assert the checks on what a present description is allowed to say."""

    def test_whitespace_only_description_is_rejected(self) -> None:
        """Reject a description the wire schema accepts but that renders as blank.

        ``NonEmptyStr`` does not strip, so a single space validates at derivation
        and reaches the operator as empty helper text. Presence alone is the
        weaker assertion.
        """
        with pytest.raises(AssertionError, match=r"no description: \['retries'\]"):
            assert_every_declared_field_is_described(_DescribesWithWhitespace)

    def test_description_naming_a_cli_flag_is_rejected(self) -> None:
        """Reject helper text that explains a field by the flag it becomes.

        The form shows a labelled control, not the command line, so a flag only
        reads to someone who already knows the tool. Matching the flag anywhere
        rather than at the start catches the copy that leads with it in every
        sense except the literal first character.
        """
        with pytest.raises(AssertionError, match=r"naming a CLI flag: \['retries'\]"):
            assert_every_declared_field_is_described(_NamesACliFlag)

    def test_description_carrying_rst_markup_is_rejected(self) -> None:
        """Reject rST inline code, which the renderer passes through as backticks."""
        with pytest.raises(AssertionError, match=r"carrying rST markup: \['retries'\]"):
            assert_every_declared_field_is_described(_CarriesRstMarkup)

    def test_a_model_declaring_no_fields_is_rejected(self) -> None:
        """Refuse to pass over an empty field set.

        Re-parenting a create model onto an intermediate base would otherwise
        make every assertion below hold without inspecting anything.
        """
        with pytest.raises(AssertionError, match=r"declares no fields of its own"):
            assert_every_declared_field_is_described(_DeclaresNothing)


class TestServedSchemaExemptions:
    """Assert the served-schema half rejects a payload that drops or adds text."""

    def test_a_declared_field_absent_from_the_schema_is_rejected(self) -> None:
        """Reject a schema that never serves a described field.

        A description that does not reach the wire is invisible to the operator,
        so model-side coverage alone is not the promise.
        """
        payload = _schema_payload({"name": "hostname", "description": None})

        with pytest.raises(
            AssertionError, match=r"absent from the schema: \['retries'\]"
        ):
            assert_schema_serves_only_declared_descriptions(payload, _DescribesOneField)

    def test_an_inherited_field_gaining_a_description_is_rejected(self) -> None:
        """Reject a description on a field the shared framework model declares.

        Describing an inherited Task field would move the schema of every other
        schema-driven app, so this form is not the place it can happen.
        """
        payload = _schema_payload(
            {"name": "retries", "description": "How many"},
            {"name": "task_name", "description": "Name this task"},
        )

        with pytest.raises(
            AssertionError, match=r"inherited fields described here: \['task_name'\]"
        ):
            assert_schema_serves_only_declared_descriptions(payload, _DescribesOneField)

    def test_a_model_declaring_no_fields_is_rejected(self) -> None:
        """Refuse to pass over an empty field set on the served-schema half too."""
        with pytest.raises(AssertionError, match=r"declares no fields of its own"):
            assert_schema_serves_only_declared_descriptions(
                _schema_payload(), _DeclaresNothing
            )
