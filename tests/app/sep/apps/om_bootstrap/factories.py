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

"""Define the DB-model factories for the OpenManager Bootstrap app's tests."""

from polyfactory import Use
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory

from app.core.utils.date_time import utc_now
from app.sep.apps.om_bootstrap.models import (
    BootstrapRun,
    BootstrapRunStatus,
    InstallMethod,
    OperatingSystem,
)


class BootstrapRunFactory(SQLAlchemyFactory[BootstrapRun]):
    """Define factory for BootstrapRun instances.

    Pinned to a running, packages-on-Ubuntu run with no hosts or run-level steps,
    so a test only spells out the fields it is actually about. ``hosts`` and
    ``run_steps`` are pinned because polyfactory cannot generate their untyped
    JSON documents, and ``finished_at``/``error`` because it would otherwise
    fill the nullable columns at random.
    """

    status = BootstrapRunStatus.RUNNING
    install_method = InstallMethod.PACKAGES
    os = OperatingSystem.UBUNTU
    mongodb_version = "8.0"
    replica_set_name = "rs-test"
    started_at = Use(utc_now)
    finished_at = None
    error = None
    hosts = Use(list)
    run_steps = Use(list)
