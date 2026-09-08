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

"""Assert helper-text coverage over the MySQL Backups create and restore forms.

Shared by the two apps' contract tests, which make the same promise about two
different forms. The check stays app-local on purpose: the other schema-driven
apps are only partly described, so promoting it to a registry-wide conformance
rule would fail them.
"""

from collections import Counter
from typing import Any

from app.sep.apps.framework.form_dsl import TaskFormModel, Ui

_RST_INLINE_CODE = "``"
_SHARED_BASE_CHAIN = frozenset(TaskFormModel.__mro__)


def _declared_names(create_model: type[TaskFormModel]) -> set[str]:
    """Return the field names the model declares itself.

    Subtracts :class:`TaskFormModel`'s own fields rather than naming the
    inherited ones, so a field added to the shared base auto-exempts and a field
    added to ``create_model`` is required to describe itself. A field re-declared
    under an inherited name is then added back: re-declaring it is how a model
    takes over its presentation, which makes it the model's to describe. The
    annotations are read off every class the model adds above the shared base, so
    splitting fields across mixins does not exempt them either.

    :param create_model: The form model to inspect.
    :return: The locally declared field names.
    """
    served = set(create_model.model_fields)
    re_declared = {
        name
        for klass in create_model.__mro__
        if klass not in _SHARED_BASE_CHAIN
        for name in vars(klass).get("__annotations__", ())
    }
    return (served - set(TaskFormModel.model_fields)) | (re_declared & served)


def _marker_descriptions(create_model: type[TaskFormModel]) -> dict[str, str]:
    """Return each declared field's ``Ui`` description text, empty when absent.

    :param create_model: The form model to inspect.
    :return: Declared field name to its description, ``""`` when the field
        carries no ``Ui`` marker or an unset description.
    """
    descriptions = {}
    for name in _declared_names(create_model):
        marker = next(
            (
                entry
                for entry in create_model.model_fields[name].metadata
                if isinstance(entry, Ui)
            ),
            None,
        )
        descriptions[name] = (marker.description if marker else None) or ""
    return descriptions


def assert_every_declared_field_is_described(
    create_model: type[TaskFormModel],
) -> None:
    """Assert each locally declared field carries usable helper text.

    Walks the field metadata, so the failure output names the fields still to
    write and a field added later cannot ship undescribed.

    :param create_model: The form model to inspect.
    :raises AssertionError: When the model declares no fields of its own, when a
        declared field has no description, when the text is blank once stripped,
        when it leads with a CLI flag the form never shows, or when it carries
        rST inline-code markup the renderer emits verbatim.
    """
    descriptions = _marker_descriptions(create_model)
    assert descriptions, (
        f"{create_model.__name__} declares no fields of its own, so every check "
        "below would pass without inspecting anything"
    )

    missing: set[str] = set()
    flag_led: set[str] = set()
    marked_up: set[str] = set()
    for name, text in descriptions.items():
        if not text.strip():
            missing.add(name)
        if text.lstrip().startswith("--"):
            flag_led.add(name)
        if _RST_INLINE_CODE in text:
            marked_up.add(name)

    assert not missing, f"fields with no description: {sorted(missing)}"
    assert not flag_led, f"descriptions leading with a CLI flag: {sorted(flag_led)}"
    assert not marked_up, f"descriptions carrying rST markup: {sorted(marked_up)}"


def assert_schema_serves_only_declared_descriptions(
    schema_payload: dict[str, Any], create_model: type[TaskFormModel]
) -> None:
    """Assert the schema serves the declared descriptions and only those.

    Guards the endpoint half of the promise: a description that never reaches the
    wire is invisible to the operator, and the inherited Task fields must stay
    undescribed here because describing them would move all the other apps'
    schemas too.

    :param schema_payload: The decoded ``GET /schema`` response body.
    :param create_model: The form model the payload derives from.
    :raises AssertionError: When one field name is served more than once, so a
        name-keyed comparison would silently read only the last entry; when the
        model declares no fields of its own; when a declared field is absent from
        the schema; when its served text differs from its marker text; or when an
        inherited field gained a description.
    """
    entries = [
        (field["name"], field.get("description") or "")
        for form in schema_payload["forms"]
        for field in form["fields"]
    ]
    repeated = sorted(
        name
        for name, count in Counter(name for name, _ in entries).items()
        if count > 1
    )
    assert not repeated, f"fields served more than once: {repeated}"

    served = dict(entries)
    declared = _marker_descriptions(create_model)
    assert declared, (
        f"{create_model.__name__} declares no fields of its own, so every check "
        "below would pass without inspecting anything"
    )

    absent = set(declared) - set(served)
    assert not absent, f"declared but absent from the schema: {sorted(absent)}"

    dropped = {name for name, text in declared.items() if served[name] != text}
    assert not dropped, f"marker text not served on the wire: {sorted(dropped)}"

    inherited = {
        name for name in set(served) & set(TaskFormModel.model_fields) if served[name]
    }
    assert not inherited, f"inherited fields described here: {sorted(inherited)}"
