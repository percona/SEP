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

"""Golden wire-format tests for the model-first form DSL.

Synthetic fixtures exercise every derivable field kind, every reference,
``allow_custom``, a whole-section ``forbidden`` hide gate, the same rule kind at
field / section / plugin scope, and discriminated-union (one-of) derivation.
Their goldens live under ``snapshots/form_dsl/`` so the ``snapshots/schema``
route-completeness check does not flag them as orphaned.
"""

from datetime import datetime
from enum import auto, StrEnum
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, Field

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.form_dsl import (
    AppFormModel,
    Choices,
    derive_app_schema,
    FieldWidget,
    Forbidden,
    FormLayout,
    FormRules,
    HostRef,
    Option,
    RemoteChoices,
    SchemaRef,
    SectionLayout,
    SectionRules,
    ServiceRef,
    TableRef,
    Ui,
)
from app.sep.apps.framework.rules import (
    CardinalityRule,
    FailRule,
    FieldGate,
    truthy,
)
from app.sep.apps.framework.schema import (
    Column,
    ListView,
)
from tests.app.sep import snapshot_utils as su


def _dump(schema) -> str:
    """Return the canonical JSON of ``schema`` under the route's dump posture."""
    return su.canonical_json(
        schema.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


class _UploadProvider(StrEnum):
    """Model a stand-in upload provider for the synthetic multi-choice field."""

    s3 = auto()
    rsync = auto()


class _SyntheticForm(AppFormModel):
    """Exercise every derivable field kind, ref, allow_custom, and rule scope."""

    a_string: Annotated[str, Ui(label="String", section="main")] = ""
    a_int: Annotated[int | None, Ui(label="Int", section="main")] = None
    a_float: Annotated[float | None, Ui(label="Float", section="main")] = None
    a_bool: Annotated[bool, Ui(label="Bool", section="main")] = False
    a_datetime: Annotated[datetime | None, Ui(label="When", section="main")] = None
    a_textarea: Annotated[
        str, Ui(label="Notes", section="main", widget=FieldWidget.TEXTAREA)
    ] = ""
    a_yaml: Annotated[
        str, Ui(label="Config", section="main", widget=FieldWidget.YAML)
    ] = ""
    a_int_choice: Annotated[
        int,
        Choices(((0, "Purge Only"), (1, "Swap & Drop"), (2, "Swap Archive & Drop"))),
        Ui(label="Archive Type", section="main"),
    ] = 0
    a_enum_choice: Annotated[_UploadProvider, Ui(label="Provider", section="main")] = (
        _UploadProvider.s3
    )
    a_multi: Annotated[list[_UploadProvider], Ui(label="Providers", section="main")]
    service_id: Annotated[
        int,
        ServiceRef(service_types=[ServiceTypeEnum.MYSQL]),
        Ui(label="Service", section="main"),
    ]
    schema_id: Annotated[
        int | None,
        SchemaRef(),
        Ui(label="Schema", section="main", depends_on="service_id"),
    ] = None
    table_id: Annotated[
        int | None,
        TableRef(),
        Ui(label="Table", section="main", depends_on="schema_id"),
    ] = None
    hostname: Annotated[
        int | str,
        HostRef(allow_custom=True),
        Ui(label="Host", section="main"),
    ]
    free_service: Annotated[
        int | str,
        ServiceRef(service_types=[ServiceTypeEnum.MYSQL], allow_custom=True),
        Ui(label="Free Service", section="main"),
    ]
    gated_field: Annotated[
        str,
        Forbidden(when=truthy("a_string")),
        Ui(label="Gated", section="gated"),
    ] = ""

    __form_rules__: ClassVar[FormRules] = FormRules(
        sections={
            "main": SectionRules(
                fail_when=(
                    FailRule(fail_when=truthy("a_bool"), error_fields=["a_bool"]),
                ),
                cardinality_rules=(
                    CardinalityRule(fields=["a_string", "a_int"], max=1),
                ),
            ),
        },
        fail_when=(FailRule(fail_when=truthy("a_yaml"), error_fields=["a_yaml"]),),
    )


_SYNTHETIC_LAYOUT = FormLayout(
    sections=[
        SectionLayout(key="main", title="Main"),
        SectionLayout(
            key="gated",
            title="Gated",
            collapsible=True,
            collapsed_by_default=True,
            forbidden=[FieldGate(when=truthy("a_string"))],
        ),
    ]
)


def _build_synthetic_schema():
    """Assemble the synthetic coverage ``AppSchema``."""
    return derive_app_schema(
        _SyntheticForm,
        _SYNTHETIC_LAYOUT,
        name="synthetic",
        display_name="Synthetic",
        list_view=ListView(columns=[Column(key="name", label="Name")]),
    )


def test_synthetic_fixture_matches_golden():
    """Snapshot the synthetic fixture's wire format under ``snapshots/form_dsl``."""
    golden = su.SNAPSHOTS_DIR / "form_dsl" / "synthetic.json"
    su.assert_or_update(golden, _dump(_build_synthetic_schema()))


def test_synthetic_fixture_attributes_rules_by_scope():
    """Assert the same rule kind serializes to field, section, and plugin scope."""
    schema = _build_synthetic_schema()
    main_section = next(section for section in schema.forms if section.title == "Main")
    gated_field = next(
        field
        for section in schema.forms
        for field in section.fields
        if field.name == "gated_field"
    )

    assert gated_field.forbidden is not None
    assert len(gated_field.forbidden) == 1
    assert main_section.fail_when is not None
    assert len(main_section.fail_when) == 1
    assert main_section.cardinality_rules is not None
    assert len(main_section.cardinality_rules) == 1
    assert schema.fail_when is not None
    assert len(schema.fail_when) == 1
    assert schema.cardinality_rules is None


class _GoldenSourceBySchema(BaseModel):
    mode: Literal["schema"] = "schema"
    source_db_id: Annotated[str, Ui(label="Source Schema", section="source")] = ""


class _GoldenSourceByQuery(BaseModel):
    mode: Literal["query"] = "query"
    source_query: Annotated[str, Ui(label="Source Query", section="source")] = ""


class _OneOfForm(AppFormModel):
    """Exercise discriminated-union derivation into a one-of group."""

    source: Annotated[
        _GoldenSourceBySchema | _GoldenSourceByQuery,
        Field(discriminator="mode"),
        Ui(
            label="Source",
            section="source",
            description="Choose how to specify source rows.",
        ),
    ] = Field(default_factory=_GoldenSourceBySchema)


_ONE_OF_LAYOUT = FormLayout(
    sections=[SectionLayout(key="source", title="Source")],
)


def _build_one_of_schema():
    """Assemble the one-of DSL fixture ``AppSchema``."""
    return derive_app_schema(
        _OneOfForm,
        _ONE_OF_LAYOUT,
        name="one_of_fixture",
        display_name="One Of Fixture",
        list_view=ListView(columns=[Column(key="name", label="Name")]),
    )


def test_one_of_fixture_matches_golden():
    """Snapshot the one-of fixture wire format under ``snapshots/form_dsl``."""
    golden = su.SNAPSHOTS_DIR / "form_dsl" / "one_of.json"
    su.assert_or_update(golden, _dump(_build_one_of_schema()))


class _DisabledChoicesForm(AppFormModel):
    """Exercise disabled-option derivation via ``Option``."""

    archive_type: Annotated[
        int,
        Choices(
            (
                (0, "Purge Only"),
                Option(
                    value=1,
                    label="Swap & Drop",
                    disabled=True,
                    disabled_reason="Not available yet",
                ),
            )
        ),
        Ui(label="Archive Type", section="main"),
    ] = 0


_DISABLED_CHOICES_LAYOUT = FormLayout(
    sections=[SectionLayout(key="main", title="Main")],
)


def _build_disabled_choices_schema():
    """Assemble the disabled-choices fixture ``AppSchema``."""
    return derive_app_schema(
        _DisabledChoicesForm,
        _DISABLED_CHOICES_LAYOUT,
        name="disabled_choices",
        display_name="Disabled Choices",
        list_view=ListView(columns=[Column(key="name", label="Name")]),
    )


def test_disabled_choices_match_golden():
    """Assert the disabled-choices fixture wire format under ``snapshots/form_dsl``."""
    golden = su.SNAPSHOTS_DIR / "form_dsl" / "disabled_choices.json"
    su.assert_or_update(golden, _dump(_build_disabled_choices_schema()))


class _MultiRefForm(AppFormModel):
    """Exercise the four multi-value reference fields, with and without allow_custom."""

    services: Annotated[
        list[int],
        ServiceRef(service_types=[ServiceTypeEnum.MYSQL], multiple=True),
        Ui(label="Services", section="main"),
    ] = Field(default_factory=list)
    free_services: Annotated[
        list[int | str],
        ServiceRef(
            service_types=[ServiceTypeEnum.MYSQL], multiple=True, allow_custom=True
        ),
        Ui(label="Free Services", section="main"),
    ] = Field(default_factory=list)
    schemas: Annotated[
        list[int],
        SchemaRef(multiple=True),
        Ui(label="Schemas", section="main", depends_on="services"),
    ] = Field(default_factory=list)
    tables: Annotated[
        list[int],
        TableRef(multiple=True),
        Ui(label="Tables", section="main", depends_on="schemas"),
    ] = Field(default_factory=list)
    hosts: Annotated[
        list[str],
        HostRef(multiple=True),
        Ui(label="Hosts", section="main"),
    ] = Field(default_factory=list)
    free_hosts: Annotated[
        list[int | str],
        HostRef(multiple=True, allow_custom=True),
        Ui(label="Free Hosts", section="main"),
    ] = Field(default_factory=list)


_MULTI_REF_LAYOUT = FormLayout(
    sections=[SectionLayout(key="main", title="Main")],
)


def _build_multi_ref_schema():
    """Assemble the multi-value reference fixture ``AppSchema``."""
    return derive_app_schema(
        _MultiRefForm,
        _MULTI_REF_LAYOUT,
        name="multi_ref",
        display_name="Multi Ref",
        list_view=ListView(columns=[Column(key="name", label="Name")]),
    )


def test_multi_ref_fixture_matches_golden():
    """Assert the multi-value reference fixture wire format under ``snapshots/form_dsl``."""
    golden = su.SNAPSHOTS_DIR / "form_dsl" / "multi_ref.json"
    su.assert_or_update(golden, _dump(_build_multi_ref_schema()))


class _RemoteChoicesForm(AppFormModel):
    """Exercise plain, cascading, and allow_custom remote_choice derivation."""

    cluster: Annotated[
        str,
        Choices((("cluster-a", "Cluster A"), ("cluster-b", "Cluster B"))),
        Ui(label="Cluster", section="main"),
    ] = "cluster-a"
    backup: Annotated[
        str,
        RemoteChoices(endpoint="/apps/restore/backups"),
        Ui(label="Backup", section="main"),
    ] = ""
    cascaded_backup: Annotated[
        str,
        RemoteChoices(endpoint="/apps/restore/backups"),
        Ui(label="Cascaded Backup", section="main", depends_on="cluster"),
    ] = ""
    custom_backup: Annotated[
        str,
        RemoteChoices(endpoint="/apps/restore/backups", allow_custom=True),
        Ui(label="Custom Backup", section="main"),
    ] = ""


_REMOTE_CHOICES_LAYOUT = FormLayout(
    sections=[SectionLayout(key="main", title="Main")],
)


def _build_remote_choices_schema():
    """Assemble the remote-choices fixture ``AppSchema``."""
    return derive_app_schema(
        _RemoteChoicesForm,
        _REMOTE_CHOICES_LAYOUT,
        name="remote_choices",
        display_name="Remote Choices",
        list_view=ListView(columns=[Column(key="name", label="Name")]),
    )


def test_remote_choices_fixture_matches_golden():
    """Assert the remote-choices fixture wire format under ``snapshots/form_dsl``."""
    golden = su.SNAPSHOTS_DIR / "form_dsl" / "remote_choices.json"
    su.assert_or_update(golden, _dump(_build_remote_choices_schema()))
