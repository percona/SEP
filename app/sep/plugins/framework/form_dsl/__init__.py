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

"""Expose the model-first form DSL: markers, ``AppFormModel``, and derivation."""

from app.sep.plugins.framework.form_dsl.conformance import check_form_conformance
from app.sep.plugins.framework.form_dsl.derivation import (
    derive_form_sections,
    derive_plugin_schema,
    find_ref_marker,
    iter_service_refs,
)
from app.sep.plugins.framework.form_dsl.markers import (
    ArgFormat,
    Choices,
    FieldWidget,
    Forbidden,
    FormLayout,
    FormRules,
    Hidden,
    HostRef,
    Requires,
    SchemaRef,
    SectionLayout,
    SectionRules,
    ServiceRef,
    TableRef,
    Ui,
)
from app.sep.plugins.framework.form_dsl.model import AppFormModel, TaskFormModel

__all__ = [
    "AppFormModel",
    "ArgFormat",
    "Choices",
    "FieldWidget",
    "Forbidden",
    "FormLayout",
    "FormRules",
    "Hidden",
    "HostRef",
    "Requires",
    "SchemaRef",
    "SectionLayout",
    "SectionRules",
    "ServiceRef",
    "TableRef",
    "TaskFormModel",
    "Ui",
    "check_form_conformance",
    "derive_form_sections",
    "derive_plugin_schema",
    "find_ref_marker",
    "iter_service_refs",
]
