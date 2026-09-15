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

"""Locate the repository's Alembic config for tests that drive migrations directly."""

__all__ = ["ALEMBIC_INI", "REPO_ROOT"]

from pathlib import Path

#: The repository root, resolved from this module's own location so a test can
#: reach it without counting its own directory depth in ``parents[N]``.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The Alembic config every track's ``Config(..., ini_section=...)`` reads.
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
