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

"""Test the Nomad step-name leaf module."""

import ast
from pathlib import Path

import pytest

import app.tasks.execution.executors.nomad.steps as steps_module
from app.tasks.execution.executors.nomad.steps import (
    LOG_CAPTURE_HOLD_DEFAULT_SECONDS,
    NOMAD_STEP_ANONYMIZE,
    NomadStep,
)

# The sync beat runs every 30 s, and a hold shorter than two of those cadences
# can expire before any sync samples the step.
TWO_SYNC_CADENCES_SECONDS = 60
EXPECTED_HOLD_DEFAULT_SECONDS = 90


def test_nomad_step_members_are_literal_wire_values() -> None:
    """Assert every NomadStep value is the exact Nomad task Name wire string."""
    assert NomadStep.RUN_SCRIPT == "run-script"
    assert NomadStep.PREPARE_ENV == "prepare-env"
    assert NomadStep.CLEAN_UP == "clean-up"
    assert NomadStep.CHECK_STALENESS == "check-staleness"
    assert NomadStep.LOG_CAPTURE_HOLD == "log-capture-hold"
    assert NomadStep.STEP1 == "step1"
    assert {member.value for member in NomadStep} == {
        "run-script",
        "prepare-env",
        "clean-up",
        "check-staleness",
        "log-capture-hold",
        "step1",
    }


def test_steps_module_imports_only_enum() -> None:
    """Assert steps.py is a pure leaf: no import of anything but ``enum``.

    Covers static (``import x`` / ``from x import y``, absolute and relative,
    aliased, nested inside any block) and dynamic (``importlib.import_module``,
    ``__import__``) forms, so a leaf violation cannot spell its way past the
    walk and report clean.
    """
    module_file = Path(steps_module.__file__)
    tree = ast.parse(module_file.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or node.level > 0:
                pytest.fail("relative import is not allowed in steps.py")
            imported_modules.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            target = node.func
            name = (
                target.attr
                if isinstance(target, ast.Attribute)
                else target.id
                if isinstance(target, ast.Name)
                else ""
            )
            if name in {"import_module", "__import__"}:
                pytest.fail(f"dynamic import via {name}() is not allowed in steps.py")
    assert imported_modules == {"enum"}


def test_nomad_step_anonymize_covers_every_member() -> None:
    """Assert anonymization classification is total over NomadStep."""
    assert set(NOMAD_STEP_ANONYMIZE) == set(NomadStep)


def test_anonymized_steps_remain_run_script_and_step1() -> None:
    """Assert effective anonymized set stays exactly run-script and step1."""
    assert NomadStep.anonymized() == frozenset({"run-script", "step1"})
    assert NOMAD_STEP_ANONYMIZE[NomadStep.RUN_SCRIPT] is True
    assert NOMAD_STEP_ANONYMIZE[NomadStep.STEP1] is True
    assert NOMAD_STEP_ANONYMIZE[NomadStep.PREPARE_ENV] is False
    assert NOMAD_STEP_ANONYMIZE[NomadStep.CLEAN_UP] is False
    assert NOMAD_STEP_ANONYMIZE[NomadStep.CHECK_STALENESS] is False
    assert NOMAD_STEP_ANONYMIZE[NomadStep.LOG_CAPTURE_HOLD] is False


def test_is_persistable_excludes_only_the_log_capture_hold_step() -> None:
    """Assert the hold step is the sole member SEP neither drains nor gates on."""
    assert not NomadStep.is_persistable(NomadStep.LOG_CAPTURE_HOLD)
    assert all(
        NomadStep.is_persistable(step)
        for step in NomadStep
        if step is not NomadStep.LOG_CAPTURE_HOLD
    )


def test_is_persistable_admits_a_step_the_enum_does_not_know() -> None:
    """Assert an unrecognized step name is treated as a producer, not dropped.

    Allocation task states are keyed by whatever the job spec declared, so a
    name absent from this enum is an unknown *producer*: excluding it would
    silently drop its output from the live viewer and leave its capture
    unclassified.
    """
    assert NomadStep.is_persistable("some-future-step")
    assert NomadStep.is_persistable("step2")


def test_log_capture_hold_default_spans_at_least_two_sync_cycles() -> None:
    """Assert the shell-fallback default outlasts two 30 s sync cadences.

    Two cycles is the floor below which a sub-cadence step can go unsampled
    entirely; the default carries a third so a beat delayed by worker backlog
    still lands inside the hold.
    """
    assert LOG_CAPTURE_HOLD_DEFAULT_SECONDS >= TWO_SYNC_CADENCES_SECONDS
    assert LOG_CAPTURE_HOLD_DEFAULT_SECONDS == EXPECTED_HOLD_DEFAULT_SECONDS
