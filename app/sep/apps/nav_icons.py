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

"""Define the closed ``NavIcon`` vocabulary shared by app definitions and the shell.

Each member's value is the icon key emitted on ``GET /api/apps`` and resolved by
the React shell's ``ICON_BY_KEY`` map to a concrete MUI component. The set is
closed -- it names the icons the frontend bundles -- so an app definition that
declares an unknown icon fails Pydantic validation at import. Members name the
icon, not the app, so apps sharing an icon share a member. The frontend mirrors
this vocabulary in an ``ICON_BY_KEY`` map; the two copies are kept in sync by
hand (no codegen), so a member added here needs the matching frontend entry or
that app silently falls back to the default sidebar icon.

This is a leaf module (only ``enum``) deliberately kept outside the
``app.sep.apps.framework`` package: ``app.sep.config`` types its ``App.NAV_ICON``
setting against ``NavIcon``, and importing anything under ``framework`` from
``config`` would close a circular import (``framework`` eagerly imports
``app.sep.deps``, which imports ``config``).
"""

from enum import StrEnum


class NavIcon(StrEnum):
    """Enumerate the sidebar icon keys the React shell bundles."""

    ASSIGNMENT = "assignment"
    CODE = "code"
    SUPPORT_AGENT = "support-agent"
    DESCRIPTION = "description"
    TROUBLESHOOT = "troubleshoot"
    TABLE_CHART = "table-chart"
    CHECK_CIRCLE = "check-circle"
    MYSQL = "mysql"
    MONGO = "mongo"
    POSTGRESQL = "postgresql"
    ARCHIVE = "archive"
    SCIENCE = "science"
    BAR_CHART = "bar-chart"
    ACCOUNT_TREE = "account-tree"
