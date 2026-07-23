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
:data:`~tests.app.sep.apps.archives.build_pins.ARCHIVES_DELETE_PINS` — a
*delete-without-archiving* create that drops the ``destination`` (and its
``host``) so the seeded source and destination table references never collide,
while the ``source`` group still exercises the generator's nested-reference
recursion. The archive-*with*-destination path is covered in-process by
``test_oneof_schema_determinism`` and by the builder-level unit tests. See the
pin module for the per-field rationale.
"""

from app.sep.apps.archives.app import app as archives_app
from tests.app.sep.apps.archives.build_pins import ARCHIVES_DELETE_PINS
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
    create_body_overrides = ARCHIVES_DELETE_PINS
