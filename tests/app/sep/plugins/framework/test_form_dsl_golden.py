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

Two strategies:

* **Real-plugin parity** — a DSL fixture reproduces the Alters plugin's schema
  and byte-compares to the route-owned ``snapshots/schema/alters.json``. This
  test never rewrites that golden (the route snapshot test owns it); it only
  reads and compares, proving the DSL emits a real plugin's exact bytes.
* **Synthetic coverage** — one fixture exercises every derivable field kind,
  every reference, ``allow_custom``, a whole-section ``forbidden`` hide gate, and
  the same rule kind at field / section / plugin scope; its golden lives under
  ``snapshots/form_dsl/`` so the ``snapshots/schema`` route-completeness check
  does not flag it as orphaned.
"""

from datetime import datetime
from enum import auto, StrEnum
from typing import Annotated, ClassVar

from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.framework.form_dsl import (
    AppFormModel,
    Choices,
    derive_plugin_schema,
    FieldWidget,
    Forbidden,
    FormLayout,
    FormRules,
    HostRef,
    Requires,
    SchemaRef,
    SectionLayout,
    SectionRules,
    ServiceRef,
    TableRef,
    Ui,
)
from app.sep.plugins.framework.rules import (
    all_,
    all_present,
    CardinalityRule,
    F,
    FailRule,
    FieldGate,
    truthy,
)
from app.sep.plugins.framework.schema import (
    Capabilities,
    ChainedPredecessor,
    Column,
    ColumnFormat,
    DerivedTask,
    DetailField,
    DetailHighlightLanguage,
    DetailSection,
    DetailView,
    ListView,
)
from tests.app.sep import snapshot_utils as su


def _dump(schema) -> str:
    """Return the canonical JSON of ``schema`` under the route's dump posture."""
    return su.canonical_json(
        schema.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


_MANUAL_TARGET_SET = all_(truthy("schema_name"), truthy("table_name"))
_INVENTORY_TARGET_SET = all_present("schema_id", "table_id")


class _AltersForm(AppFormModel):
    """Reproduce the Alters create form as a model-first DSL fixture."""

    task_name: Annotated[str, Ui(label="Task Name", section="task")]
    hostname: Annotated[str, HostRef(), Ui(label="Executor Host", section="task")]
    service_id: Annotated[
        int,
        ServiceRef(service_types=[ServiceTypeEnum.MYSQL]),
        Ui(label="Database Host", section="task"),
    ]
    pre_checks_mysql_config_file: Annotated[
        str,
        Ui(
            label="MySQL Defaults File",
            section="task",
            description=(
                "Path on the executor with [client] user/password. Pre-checks "
                "always use this path. Execute/dry-run use the same path only "
                "when not ~/.my.cnf."
            ),
        ),
    ] = "~/.my.cnf"

    schema_id: Annotated[
        int | None,
        SchemaRef(),
        Forbidden(when=_MANUAL_TARGET_SET),
        Ui(label="Schema", section="data", depends_on="service_id"),
    ] = None
    table_id: Annotated[
        int | None,
        TableRef(),
        Forbidden(when=_MANUAL_TARGET_SET),
        Ui(label="Table", section="data", depends_on="schema_id"),
    ] = None
    schema_name: Annotated[
        str | None,
        Forbidden(when=_INVENTORY_TARGET_SET),
        Ui(
            label="Schema Name",
            section="data",
            description="Manual schema name when not selecting from inventory",
        ),
    ] = None
    table_name: Annotated[
        str | None,
        Forbidden(when=_INVENTORY_TARGET_SET),
        Ui(
            label="Table Name",
            section="data",
            description="Manual table name when not selecting from inventory",
        ),
    ] = None

    alter: Annotated[
        str,
        Ui(
            label="Alter",
            section="alter",
            widget=FieldWidget.TEXTAREA,
            description=(
                "Schema modifications excluding ALTER TABLE keywords "
                "(e.g. ADD COLUMN new_col INT, DROP COLUMN old_col)"
            ),
        ),
    ]

    recursion_method: Annotated[
        str,
        Choices(
            (
                ("processlist", "Processlist"),
                ("hosts", "Hosts"),
                ("dsn", "DSN"),
                ("none", "None"),
            )
        ),
        Ui(label="Recursion Method", section="recursion", required=True),
    ] = "processlist"
    dsn_table: Annotated[
        str,
        Requires(when=F("recursion_method") == "dsn"),
        Forbidden(when=F("recursion_method") != "dsn"),
        Ui(
            label="DSN Table",
            section="recursion",
            description="Required when recursion method is 'dsn'",
        ),
    ] = "D=percona,t=dsns"

    print_arg: Annotated[
        bool,
        Ui(
            label="Print", section="flags", description="Print SQL statements to STDOUT"
        ),
    ] = False
    progress: Annotated[
        str,
        Ui(
            label="Progress",
            section="flags",
            description="Print progress reports to STDERR (e.g. time,10)",
        ),
    ] = "time,10"
    no_swap_tables: Annotated[
        bool,
        Ui(
            label="No Swap Tables",
            section="flags",
            description="Simulate without swapping the original and new table",
        ),
    ] = False
    no_drop_old_table: Annotated[
        bool,
        Ui(
            label="No Drop Old Table",
            section="flags",
            description="Keep the original table after rename",
        ),
    ] = False
    no_drop_new_table: Annotated[
        bool,
        Ui(
            label="No Drop New Table",
            section="flags",
            description="Keep the new table if copying the original fails",
        ),
    ] = False
    no_drop_triggers: Annotated[
        bool,
        Ui(
            label="No Drop Triggers",
            section="flags",
            description="Do not drop triggers on the old table",
        ),
    ] = False

    pause_file: Annotated[
        str | None,
        Ui(
            label="Pause File",
            section="advanced",
            description="Execution pauses while this file exists",
        ),
    ] = None
    new_table_name: Annotated[
        str | None,
        Ui(
            label="New Table Name",
            section="advanced",
            description="New table name before swap (%T includes original name)",
        ),
    ] = None
    tries: Annotated[
        str | None,
        Ui(
            label="Tries",
            section="advanced",
            description=(
                "Retries and wait times for critical operations "
                "(operation:tries:wait, comma-separated)"
            ),
        ),
    ] = None
    set_vars: Annotated[
        str | None,
        Ui(
            label="Set Vars",
            section="advanced",
            description="MySQL variables to set (comma-separated key=value pairs)",
        ),
    ] = None
    critical_load: Annotated[
        str | None,
        Ui(
            label="Critical Load",
            section="advanced",
            description="Abort when GLOBAL STATUS variables exceed thresholds",
        ),
    ] = None
    max_load: Annotated[
        str | None,
        Ui(
            label="Max Load",
            section="advanced",
            description="Pause when GLOBAL STATUS variables exceed thresholds",
        ),
    ] = None
    chunk_time: Annotated[
        str | None,
        Ui(
            label="Chunk Time",
            section="advanced",
            description="Target execution time per chunk in seconds",
        ),
    ] = None
    max_lag: Annotated[
        str | None,
        Ui(
            label="Max Lag",
            section="advanced",
            description="Pause until replica lag falls below this value (seconds)",
        ),
    ] = None
    max_flow_ctl: Annotated[
        str | None,
        Ui(
            label="Max Flow Control",
            section="advanced",
            description="Pause when PXC flow control exceeds this value",
        ),
    ] = None
    extra_args: Annotated[
        str | None,
        Ui(
            label="Extra Args",
            section="advanced",
            description="Additional pt-online-schema-change arguments",
        ),
    ] = None
    alert_on_fail: Annotated[
        bool,
        Ui(
            label="Alert on Fail",
            section="advanced",
            description="Send an alert if the task fails",
        ),
    ] = False
    continue_on_pre_check_failure: Annotated[
        bool,
        Ui(
            label="Continue on Pre-Check Failure",
            section="advanced",
            description=(
                "When enabled, continue to the run task even if pre-checks fail "
                "(overrides the default halt policy)"
            ),
        ),
    ] = False

    __form_rules__: ClassVar[FormRules] = FormRules(
        sections={
            "data": SectionRules(
                fail_when=(
                    FailRule(
                        fail_when=all_(
                            ~_INVENTORY_TARGET_SET,
                            ~_MANUAL_TARGET_SET,
                        ),
                        error_fields=[
                            "schema_id",
                            "table_id",
                            "schema_name",
                            "table_name",
                        ],
                        message=(
                            "Either both schema_id and table_id or both "
                            "schema_name and table_name must be provided."
                        ),
                    ),
                    FailRule(
                        fail_when=all_(_INVENTORY_TARGET_SET, _MANUAL_TARGET_SET),
                        error_fields=[
                            "schema_id",
                            "table_id",
                            "schema_name",
                            "table_name",
                        ],
                        message=(
                            "Cannot use both schema_id/table_id and "
                            "schema_name/table_name at the same time."
                        ),
                    ),
                ),
            ),
        },
    )


_ALTERS_LAYOUT = FormLayout(
    sections=[
        SectionLayout(key="task", title="Task"),
        SectionLayout(key="data", title="Data"),
        SectionLayout(key="alter", title="Alter"),
        SectionLayout(key="recursion", title="Recursion"),
        SectionLayout(key="flags", title="Flags"),
        SectionLayout(key="advanced", title="Advanced"),
    ]
)


def _build_alters_schema():
    """Assemble the DSL-derived Alters ``PluginSchema``."""
    return derive_plugin_schema(
        _AltersForm,
        _ALTERS_LAYOUT,
        name="alters",
        display_name="Alters",
        description=(
            "Run pt-online-schema-change to perform online MySQL schema modifications."
        ),
        capabilities=Capabilities(
            chaining=True, alert_on_fail=True, scheduling=True, stats=True
        ),
        list_view=ListView(
            columns=[
                Column(key="name", label="Name", sortable=True),
                Column(key="status", label="Status", format=ColumnFormat.STATUS),
                Column(
                    key="service_type",
                    label="Service Type",
                    format=ColumnFormat.CHIP,
                ),
                Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
                Column(key="created_by", label="Created By"),
            ],
        ),
        detail_view=DetailView(
            sections=[
                DetailSection(
                    title="Execution",
                    fields=[
                        DetailField(
                            path="data.meta._command_line",
                            label="Command line",
                            highlight=DetailHighlightLanguage.BASH,
                        ),
                        DetailField(path="data.meta.target", label="Target"),
                        DetailField(path="data.meta._schema_name", label="Schema"),
                        DetailField(path="data.meta._table_name", label="Table"),
                    ],
                ),
            ],
        ),
        derived=[
            DerivedTask(
                name_suffix="-dry-run",
                arg_substitutions={"--execute": "--dry-run"},
            ),
        ],
        predecessors=[
            ChainedPredecessor(name_suffix="-pre-checks", on_failure="halt"),
        ],
    )


def test_alters_parity_byte_compares_to_route_golden():
    """Assert the DSL-derived Alters schema matches the route golden byte-for-byte."""
    golden = su.SNAPSHOTS_DIR / "schema" / "alters.json"
    derived = _dump(_build_alters_schema())
    assert derived == golden.read_text(encoding="utf-8"), (
        "DSL-derived Alters schema drifted from the route-owned alters.json; "
        "the DSL no longer reproduces the hand-written schema byte-for-byte"
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
    """Assemble the synthetic coverage ``PluginSchema``."""
    return derive_plugin_schema(
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
