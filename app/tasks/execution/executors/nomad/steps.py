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

"""Define the canonical Nomad task/step names used inside Nomad job specs.

This module is a pure leaf: it imports nothing beyond ``enum`` so callers can
name a step without constructing the Nomad executor. Wire values are spelled
literally (no ``auto()``) so the Nomad task ``Name`` is never implicit.
"""

from enum import StrEnum


class NomadStep(StrEnum):
    """Represent Nomad task ``Name`` values used by SEP job-spec templates.

    ``STEP1`` is legacy — only historical task logs / the frozen Alembic
    migration still emit it. Do not wire new job specs to ``step1``.
    """

    RUN_SCRIPT = "run-script"
    PREPARE_ENV = "prepare-env"
    CLEAN_UP = "clean-up"
    CHECK_STALENESS = "check-staleness"
    STEP1 = "step1"

    @classmethod
    def anonymized(cls) -> frozenset["NomadStep"]:
        """Return the steps whose log output is PII-anonymized.

        :return: The frozen set of steps classified as anonymized.
        """
        return frozenset(
            step for step, anonymize in NOMAD_STEP_ANONYMIZE.items() if anonymize
        )


NOMAD_STEP_ANONYMIZE: dict[NomadStep, bool] = {
    NomadStep.RUN_SCRIPT: True,
    NomadStep.PREPARE_ENV: False,
    NomadStep.CLEAN_UP: False,
    NomadStep.CHECK_STALENESS: False,
    NomadStep.STEP1: True,
}
