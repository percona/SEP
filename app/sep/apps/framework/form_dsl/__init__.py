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

"""Expose the model-first form DSL: markers, ``AppFormModel``, derivation, and the Percona-Toolkit reverse-parser helpers."""

from app.sep.apps.framework.form_dsl.conformance import check_form_conformance
from app.sep.apps.framework.form_dsl.derivation import (
    derive_app_schema,
    derive_form_sections,
    find_ref_marker,
    iter_service_refs,
)
from app.sep.apps.framework.form_dsl.markers import (
    ArgFormat,
    Choices,
    FieldWidget,
    find_arg_format,
    Forbidden,
    FormLayout,
    FormRules,
    Hidden,
    HostRef,
    Option,
    Requires,
    resolve_arg_template,
    SchemaRef,
    SectionLayout,
    SectionRules,
    ServiceRef,
    TableRef,
    Ui,
)
from app.sep.apps.framework.form_dsl.model import AppFormModel, TaskFormModel
from app.sep.apps.framework.form_dsl.pt_toolkit import (
    derive_arg_parser_from_model,
    DSN_TABLE_DEFAULT,
    make_arg_parser,
)

__all__ = [
    "DSN_TABLE_DEFAULT",
    "AppFormModel",
    "ArgFormat",
    "Choices",
    "FieldWidget",
    "Forbidden",
    "FormLayout",
    "FormRules",
    "Hidden",
    "HostRef",
    "Option",
    "Requires",
    "SchemaRef",
    "SectionLayout",
    "SectionRules",
    "ServiceRef",
    "TableRef",
    "TaskFormModel",
    "Ui",
    "check_form_conformance",
    "derive_app_schema",
    "derive_arg_parser_from_model",
    "derive_form_sections",
    "find_arg_format",
    "find_ref_marker",
    "iter_service_refs",
    "make_arg_parser",
    "resolve_arg_template",
]
