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

"""Run the derived-router contract suite against the migrated Archives app.

Archives is the first one-of (discriminated-union) create model bound to the
shared :class:`DerivedRouterContractTests`. The generic body generator recurses
into the ``source`` / ``destination`` / ``host`` union groups and resolves their
nested inventory references against the seeded mock inventory; the app-specific
values the generic generator cannot infer are pinned through
``create_body_overrides``:

* ``delete_data`` / ``destination`` — a *delete-without-archiving* create, so no
  destination is posted. The generator seeds both the source and destination table
  references from the one seeded ``MOCK_CREATED_TABLE_ID``, which the route's
  "source and destination tables cannot be the same" rule rejects; dropping the
  destination sidesteps the collision while the ``source`` and ``host`` groups still
  exercise the generator's nested-reference recursion. Setting ``delete_data`` keeps
  the ``_check_destination_presence`` validator satisfied with an absent destination.
  The same-table rule itself is covered by the archives dep tests.
* ``swap_drop`` — the ``__form_rules__`` ``FailRule`` accepts only ``PURGE_ONLY``.
* ``where`` — the field's ``Requires`` rule makes it mandatory unless ``SWAP_DROP``.
"""

from app.sep.apps.archives.app import app as archives_app
from app.sep.apps.archives.constants import SwapDropEnum
from tests.app.sep.apps.framework.contract_suite import DerivedRouterContractTests


class TestArchivesContract(DerivedRouterContractTests):
    """Assert the archives app's full derived HTTP surface, knob by knob.

    ``remapped_username`` is ``None``: the app's context provider is the real
    Casdoor ``get_username_mapping``, which is not deterministic under test, so the
    injected-extras tests assert only the deterministic ``service_type`` — matching
    the ``alters`` and ``checksums`` subclasses.
    """

    app_def = archives_app
    remapped_username = None
    create_body_overrides = {
        "swap_drop": SwapDropEnum.PURGE_ONLY,
        "where": "id < 100",
        "delete_data": True,
        "destination": None,
    }
