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

"""Define the Alembic locations and revision ids the migration tests share."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

# The create_alert_backup_table revision: the head of the alerts branch, the
# app the PMM-embedded side-car's allow-list strip removes.
ALERTS_HEAD = "d21ad387df7a"
# A revision id no branch in the tree defines, standing in for version skew.
UNKNOWN_REVISION = "deadbeef1234"
