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

"""Define shared fixtures and helpers for report plugin tests."""

from datetime import datetime, UTC
from typing import Any

from app.sep.apps.report.models import ReportData, ReportMetadata


def make_report(**overrides: Any) -> ReportData:
    """Build a minimal ``ReportData`` with sensible defaults."""
    defaults = {
        "metadata": ReportMetadata(
            title="Weekly Health Report",
            generated_at=datetime(2026, 3, 31, 12, 0, 0, tzinfo=UTC),
            report_week="2026 - Week 14",
            report_interval="now-7d to now",
        ),
    }
    defaults.update(overrides)
    return ReportData(**defaults)
