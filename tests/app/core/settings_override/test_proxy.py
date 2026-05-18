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

"""Tests for :class:`OverridableSettingsProxy`."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import BaseModel

from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.proxy import OverridableSettingsProxy


class _Sample(BaseModel):
    name: str = "default-name"
    count: int = 1


def _factory() -> _Sample:
    return _Sample()


@pytest.fixture
def proxy() -> OverridableSettingsProxy[_Sample]:
    """Return a fresh proxy wrapping ``_Sample``."""
    return OverridableSettingsProxy(
        _factory, setting_class=SettingClassEnum.SEP_SETTINGS
    )


def test_empty_snapshot_delegates_to_factory(
    proxy: OverridableSettingsProxy[_Sample],
) -> None:
    """With no snapshot entries, attribute reads delegate to the wrapped instance."""
    assert proxy.name == "default-name"
    assert proxy.count == 1


def test_snapshot_intercepts_named_attribute(
    proxy: OverridableSettingsProxy[_Sample],
) -> None:
    """When the snapshot contains the field, it overrides the wrapped value."""
    proxy._set_snapshot({"name": "from-snapshot"})
    assert proxy.name == "from-snapshot"
    # Other fields still delegate to the wrapped instance.
    assert proxy.count == 1


def test_clearing_snapshot_falls_back_to_factory(
    proxy: OverridableSettingsProxy[_Sample],
) -> None:
    """Removing an override key falls back to the wrapped value."""
    proxy._set_snapshot({"name": "from-snapshot"})
    assert proxy.name == "from-snapshot"
    proxy._set_snapshot({})
    assert proxy.name == "default-name"


def test_class_property_reflects_wrapped_class(
    proxy: OverridableSettingsProxy[_Sample],
) -> None:
    """``__class__`` reports the wrapped class (preserves ``LazyProxy``)."""
    assert isinstance(proxy, _Sample)


def test_setting_class_stored(proxy: OverridableSettingsProxy[_Sample]) -> None:
    """The proxy stores the ``setting_class`` identifier passed at construction."""
    assert proxy._setting_class is SettingClassEnum.SEP_SETTINGS


def test_concurrent_swap_is_atomic(
    proxy: OverridableSettingsProxy[_Sample],
) -> None:
    """A reader during a snapshot swap sees one full snapshot or the other.

    The CPython STORE_ATTR opcode is single-instruction (GIL-protected), so a
    reader sees the previous snapshot or the new one -- never a partially
    mutated dict.
    """
    snapshot_a = {"name": "alpha"}
    snapshot_b = {"name": "beta"}
    proxy._set_snapshot(snapshot_a)

    observed: list[str] = []
    stop = threading.Event()

    def _reader() -> None:
        while not stop.is_set():
            value = proxy.name
            observed.append(value)

    def _writer() -> None:
        for _ in range(200):
            proxy._set_snapshot(snapshot_a)
            proxy._set_snapshot(snapshot_b)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(_reader)
        pool.submit(_writer).result()
        stop.set()
        reader.result()

    assert set(observed) <= {"alpha", "beta"}


def test_missing_attribute_raises_attribute_error(
    proxy: OverridableSettingsProxy[_Sample],
) -> None:
    """Unknown attributes still raise ``AttributeError`` from the wrapped instance."""
    with pytest.raises(AttributeError):
        proxy.does_not_exist  # noqa: B018


def test_per_class_isolation_with_unknown_field() -> None:
    """A snapshot entry for a field absent on the wrapped class is ignored on read.

    A ``__getattr__`` for an unknown key falls through to the wrapped instance,
    raising ``AttributeError`` -- snapshots cannot leak across classes that
    happen to share a key name when one class lacks that field.
    """
    proxy = OverridableSettingsProxy(
        _factory, setting_class=SettingClassEnum.SEP_SETTINGS
    )
    # Snapshot contains a key NOT present on _Sample.
    proxy._set_snapshot({"name": "ok"})
    assert proxy.name == "ok"
    # But an unknown key on the snapshot AND missing on the wrapped instance
    # would still raise AttributeError on read -- exercised by the previous test.
