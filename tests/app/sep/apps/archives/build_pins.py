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

"""Provide the canonical archives create-body pins shared by the contract tests.

The archives one-of create model carries a ``__form_rules__`` rule and a model
validator the generic Polyfactory body generator cannot satisfy unaided, so the
contract tests pin the constrained scalars. Both variants derive from one base so
a newly-constrained field is added in a single place:

* :data:`ARCHIVES_ARCHIVE_PINS` — an archive-*with*-destination build:
  ``delete_data`` falsy, leaving ``source`` / ``destination`` / ``host`` for the
  body generator's union recursion to populate. Used by the builder-level unit
  tests and the branch-selection probe.
* :data:`ARCHIVES_DELETE_PINS` — a delete-*without*-archiving create:
  ``delete_data`` set, and ``destination`` / ``host`` dropped, so the seeded
  source and destination table references never collide on the one seeded table
  id. Used by the ``TestArchivesContract`` HTTP contract subclass.

Pins by field:

* ``swap_drop`` — the ``__form_rules__`` ``FailRule`` accepts only ``PURGE_ONLY``.
* ``where`` — the field's ``Requires`` rule makes it mandatory unless ``SWAP_DROP``.
"""

from typing import Any

from app.sep.apps.archives.constants import SwapDropEnum

_ARCHIVES_BASE_PINS: dict[str, Any] = {
    "swap_drop": SwapDropEnum.PURGE_ONLY,
    "where": "id < 100",
}

# ``delete_data`` falsy keeps ``_check_destination_presence`` satisfied with the
# generator-populated destination branch, so the union recursion stays observable.
ARCHIVES_ARCHIVE_PINS: dict[str, Any] = {**_ARCHIVES_BASE_PINS, "delete_data": None}

# ``delete_data`` set drops the destination (and its host) so the seeded source and
# destination table references never collide on the one seeded ``MOCK_CREATED_TABLE_ID``,
# which the route's "source and destination tables cannot be the same" rule rejects.
ARCHIVES_DELETE_PINS: dict[str, Any] = {
    **_ARCHIVES_BASE_PINS,
    "delete_data": True,
    "destination": None,
    "host": None,
}
