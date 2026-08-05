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

"""Define the model factories for the Archives app's tests.

No test consumes this yet; the app's tests pin the create body through
:mod:`tests.app.sep.apps.archives.build_pins`.
"""

from polyfactory.factories.pydantic_factory import ModelFactory

from app.sep.apps.archives.models import ArchivesCreate


class ArchivesCreateFactory(ModelFactory[ArchivesCreate]):
    """Define factory for ArchivesCreate instances."""
