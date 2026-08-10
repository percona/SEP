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

"""Tests for the Nomad step-name leaf module."""

import ast
from pathlib import Path

import pytest

from app.tasks.execution.executors.nomad.steps import (
    NOMAD_STEP_ANONYMIZE,
    NomadStep,
)


def test_nomad_step_members_are_literal_wire_values() -> None:
    """Assert every NomadStep value is the exact Nomad task Name wire string."""
    assert NomadStep.RUN_SCRIPT == "run-script"
    assert NomadStep.PREPARE_ENV == "prepare-env"
    assert NomadStep.CLEAN_UP == "clean-up"
    assert NomadStep.CHECK_STALENESS == "check-staleness"
    assert NomadStep.STEP1 == "step1"
    assert {member.value for member in NomadStep} == {
        "run-script",
        "prepare-env",
        "clean-up",
        "check-staleness",
        "step1",
    }


def test_steps_module_imports_only_enum() -> None:
    """Assert steps.py is a pure leaf: only ``enum`` appears in import statements."""
    import app.tasks.execution.executors.nomad.steps as steps_module

    module_file = Path(steps_module.__file__)
    tree = ast.parse(module_file.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                pytest.fail("relative import without module is not allowed in steps.py")
            imported_modules.add(node.module.split(".")[0])
    assert imported_modules == {"enum"}


def test_nomad_step_anonymize_covers_every_member() -> None:
    """Assert anonymization classification is total over NomadStep."""
    assert set(NOMAD_STEP_ANONYMIZE) == set(NomadStep)


def test_anonymized_steps_remain_run_script_and_step1() -> None:
    """Assert effective anonymized set stays exactly run-script and step1."""
    derived = frozenset(
        step.value for step, anonymize in NOMAD_STEP_ANONYMIZE.items() if anonymize
    )
    assert derived == frozenset({"run-script", "step1"})
    assert NOMAD_STEP_ANONYMIZE[NomadStep.RUN_SCRIPT] is True
    assert NOMAD_STEP_ANONYMIZE[NomadStep.STEP1] is True
    assert NOMAD_STEP_ANONYMIZE[NomadStep.PREPARE_ENV] is False
    assert NOMAD_STEP_ANONYMIZE[NomadStep.CLEAN_UP] is False
    assert NOMAD_STEP_ANONYMIZE[NomadStep.CHECK_STALENESS] is False
