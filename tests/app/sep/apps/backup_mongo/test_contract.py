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

"""Run the shared derived-router contract suite against the backup_mongo definition."""

from app.sep.apps.backup_mongo.app import app as backup_mongo_app
from tests.app.sep.apps.framework.contract_suite import DerivedRouterContractTests


class TestBackupMongoContract(DerivedRouterContractTests):
    """Bind the backup_mongo ``TaskExecutionApp`` to the shared contract suite."""

    app_def = backup_mongo_app
