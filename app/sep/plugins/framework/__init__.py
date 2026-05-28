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

"""Provide shared building blocks for schema-driven plugins."""

from app.sep.plugins.framework.cascade import (
    build_derived_payload,
    build_predecessor_payload,
    cascade_create_predecessors,
    cascade_create_tasks,
    cascade_delete_predecessors,
    cascade_delete_tasks,
    cascade_update_predecessors,
    cascade_update_tasks,
    CascadeFailure,
    CascadeResult,
)
from app.sep.plugins.framework.connectivity import (
    ConnectivityWarning,
    maybe_record_connectivity_warning,
    record_connectivity_warning,
)
from app.sep.plugins.framework.rules import (
    absent,
    all_,
    all_equal,
    all_falsy,
    all_present,
    all_truthy,
    any_,
    any_falsy,
    any_present,
    any_truthy,
    apply_conditional_rules,
    CardinalityRule,
    ConditionalRulesModel,
    evaluate_conditional_rules,
    F,
    FailRule,
    falsy,
    FieldExpr,
    FieldGate,
    none_present,
    not_,
    Predicate,
    present,
    truthy,
    xor_,
)
from app.sep.plugins.framework.task_status import extract_latest_task_status

__all__ = [
    "CardinalityRule",
    "CascadeFailure",
    "CascadeResult",
    "ConditionalRulesModel",
    "ConnectivityWarning",
    "F",
    "FailRule",
    "FieldExpr",
    "FieldGate",
    "Predicate",
    "absent",
    "all_",
    "all_equal",
    "all_falsy",
    "all_present",
    "all_truthy",
    "any_",
    "any_falsy",
    "any_present",
    "any_truthy",
    "apply_conditional_rules",
    "build_derived_payload",
    "build_predecessor_payload",
    "cascade_create_predecessors",
    "cascade_create_tasks",
    "cascade_delete_predecessors",
    "cascade_delete_tasks",
    "cascade_update_predecessors",
    "cascade_update_tasks",
    "evaluate_conditional_rules",
    "extract_latest_task_status",
    "falsy",
    "maybe_record_connectivity_warning",
    "none_present",
    "not_",
    "present",
    "record_connectivity_warning",
    "truthy",
    "xor_",
]
