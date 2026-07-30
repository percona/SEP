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

"""Test the transitional conformance check between a create model and its schema."""

from pydantic import BaseModel

from app.sep.apps.framework.form_dsl import check_form_conformance
from app.sep.apps.framework.schema import (
    AppSchema,
    Column,
    FormSection,
    IntegerField,
    ListView,
    StringField,
)


def _schema(*fields) -> AppSchema:
    """Return a minimal task-style schema whose single section holds ``fields``."""
    return AppSchema(
        name="p",
        display_name="P",
        forms=[FormSection(title="S", fields=list(fields))],
        list_view=ListView(columns=[Column(key="name", label="Name")]),
    )


class _AgreeModel(BaseModel):
    name: str
    count: int = 0


def test_silent_on_full_agreement():
    """Assert no disagreements when presence, kind, required, and default align."""
    schema = _schema(
        StringField(name="name", label="Name", required=True),
        IntegerField(name="count", label="Count", required=False, default=0),
    )
    assert check_form_conformance(_AgreeModel, schema) == []


class _MissingModel(BaseModel):
    only_model: str = ""


def test_flags_field_presence_disagreements():
    """Assert fields present on only one side are reported."""
    schema = _schema(StringField(name="only_schema", label="Only", required=False))
    warnings = check_form_conformance(_MissingModel, schema)
    assert any("only_model" in message for message in warnings)
    assert any("only_schema" in message for message in warnings)


class _KindModel(BaseModel):
    flag: bool = False


def test_flags_kind_disagreement():
    """Assert a scalar kind mismatch (model bool vs schema integer) is reported."""
    schema = _schema(IntegerField(name="flag", label="Flag", required=False))
    warnings = check_form_conformance(_KindModel, schema)
    assert any("flag" in message and "kind" in message for message in warnings)


class _RequiredModel(BaseModel):
    thing: str


def test_flags_required_disagreement():
    """Assert a required-ness mismatch is reported."""
    schema = _schema(StringField(name="thing", label="Thing", required=False))
    warnings = check_form_conformance(_RequiredModel, schema)
    assert any("thing" in message and "required" in message for message in warnings)


class _DefaultModel(BaseModel):
    label_text: str = "x"


def test_flags_default_disagreement_against_unset_schema_default():
    """Assert a model default drifting from an unset schema default is reported."""
    schema = _schema(StringField(name="label_text", label="Label", required=False))
    warnings = check_form_conformance(_DefaultModel, schema)
    assert any("label_text" in message and "default" in message for message in warnings)
