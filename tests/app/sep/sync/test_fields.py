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

"""Define tests for the app.sep.sync.fields module."""

import importlib
import pkgutil
from collections.abc import Iterator

from annotated_types import BaseMetadata
from pydantic import TypeAdapter

from app.sep.sync import syncers
from app.sep.sync.fields import CONSTRAINED_SYNCER_FIELDS
from app.sep.sync.models import BaseSyncer
from app.sep.sync.syncers.pmm import PMMSyncer


def _syncer_classes() -> set[type[BaseSyncer]]:
    """Return ``BaseSyncer`` and every syncer class deriving from it.

    Every module under ``app.sep.sync.syncers`` is imported first: subclass discovery
    only sees classes something has already imported, so leaving that to the ambient
    import graph would narrow the set silently the day an unrelated import moves.

    :return: The syncer classes whose fields a configured extra key can land on.
    """
    for module in pkgutil.walk_packages(syncers.__path__, f"{syncers.__name__}."):
        importlib.import_module(module.name)

    def descendants(cls: type[BaseSyncer]) -> Iterator[type[BaseSyncer]]:
        for subclass in cls.__subclasses__():
            yield subclass
            yield from descendants(subclass)

    return {BaseSyncer, *descendants(BaseSyncer)}


class TestConstrainedSyncerFields:
    """Keep the load-time check in step with the fields it stands in for."""

    def test_every_syncer_module_is_discoverable(self):
        """Prove the discovery the drift guard rests on actually finds syncers."""
        assert {PMMSyncer, BaseSyncer} <= _syncer_classes()  # vacuous-ok: fixed rhs

    def test_registry_covers_every_constrained_syncer_field(self):
        """Fail when a new constrained threshold lands without a load-time check.

        An unregistered one is only checked at syncer construction, which for the
        request-scoped dependency means once per request instead of once at load.
        """
        constrained = {
            name
            for cls in _syncer_classes()
            for name, field in cls.model_fields.items()
            if any(isinstance(item, BaseMetadata) for item in field.metadata)
        }

        assert constrained, "no constrained syncer field was discovered"
        assert constrained <= set(CONSTRAINED_SYNCER_FIELDS)

    def test_registry_holds_no_field_no_syncer_declares(self):
        """Drop an entry whose field a syncer no longer carries."""
        declared = {name for cls in _syncer_classes() for name in cls.model_fields}

        assert set(CONSTRAINED_SYNCER_FIELDS) <= declared

    def test_registry_entries_mirror_the_fields_they_stand_for(self):
        """Validate against the very types the syncer fields declare."""
        owners = {
            name: cls
            for cls in _syncer_classes()
            for name in cls.model_fields
            if name in CONSTRAINED_SYNCER_FIELDS
        }

        assert set(owners) == set(CONSTRAINED_SYNCER_FIELDS)
        for name, cls in owners.items():
            declared = TypeAdapter(cls.model_fields[name].rebuild_annotation())
            assert (
                CONSTRAINED_SYNCER_FIELDS[name].adapter.core_schema
                == declared.core_schema
            ), name

    def test_every_entry_names_the_forms_it_accepts(self):
        """Give the operator something to act on, not just a refusal."""
        assert all(
            constraint.accepted.strip()
            for constraint in CONSTRAINED_SYNCER_FIELDS.values()
        )
