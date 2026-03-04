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

"""Test the LazyProxy utility."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.utils.lazy import LazyProxy

INITIAL_VALUE = 42
UPDATED_VALUE = 99
PATCHED_VALUE = 999


class _DummySettings:
    """Minimal stand-in for a settings object."""

    def __init__(self) -> None:
        self.value = INITIAL_VALUE
        self.name = "test"


class TestLazyProxyDeferredInstantiation:
    """Verify the factory is NOT called until an attribute is accessed."""

    def test_factory_not_called_on_creation(self) -> None:
        """Assert factory is not invoked at proxy construction time."""
        factory = MagicMock(return_value=_DummySettings())
        LazyProxy(factory)
        factory.assert_not_called()

    def test_factory_called_on_first_access(self) -> None:
        """Assert factory is invoked on the first attribute access."""
        factory = MagicMock(return_value=_DummySettings())
        proxy = LazyProxy(factory)

        _ = proxy.value

        factory.assert_called_once()

    def test_factory_called_only_once(self) -> None:
        """Assert factory is called exactly once across multiple accesses."""
        factory = MagicMock(return_value=_DummySettings())
        proxy = LazyProxy(factory)

        _ = proxy.value
        _ = proxy.name
        _ = proxy.value

        factory.assert_called_once()


class TestLazyProxyAttributeDelegation:
    """Verify attribute access delegates to the real instance."""

    def test_getattr_returns_instance_attribute(self) -> None:
        """Assert proxy returns attributes from the wrapped instance."""
        proxy = LazyProxy(_DummySettings)

        assert proxy.value == INITIAL_VALUE
        assert proxy.name == "test"

    def test_setattr_delegates_to_instance(self) -> None:
        """Assert setting attributes on the proxy sets them on the instance."""
        proxy = LazyProxy(_DummySettings)
        _ = proxy.value

        proxy.value = UPDATED_VALUE

        assert proxy.value == UPDATED_VALUE

    def test_delattr_delegates_to_instance(self) -> None:
        """Assert deleting attributes on the proxy deletes them on the instance."""
        proxy = LazyProxy(_DummySettings)
        _ = proxy.value

        del proxy.value

        with pytest.raises(AttributeError):
            _ = proxy.value

    def test_setattr_triggers_resolution(self) -> None:
        """Assert setting an attribute on an unresolved proxy resolves it first."""
        factory = MagicMock(return_value=_DummySettings())
        proxy = LazyProxy(factory)

        proxy.value = UPDATED_VALUE

        factory.assert_called_once()
        assert proxy.value == UPDATED_VALUE


class TestLazyProxyIsinstance:
    """Verify isinstance() works transparently via __class__ delegation."""

    def test_isinstance_returns_true(self) -> None:
        """Assert isinstance matches the wrapped type after resolution."""
        proxy = LazyProxy(_DummySettings)

        assert isinstance(proxy, _DummySettings)

    def test_isinstance_triggers_resolution(self) -> None:
        """Assert isinstance resolves the proxy to check the class."""
        factory = MagicMock(return_value=_DummySettings())
        proxy = LazyProxy(factory)

        isinstance(proxy, _DummySettings)

        factory.assert_called_once()


class TestLazyProxyRepr:
    """Verify repr shows useful information."""

    def test_repr_before_resolution(self) -> None:
        """Assert repr shows unresolved state before first access."""
        proxy = LazyProxy(_DummySettings)

        result = repr(proxy)

        assert "LazyProxy" in result
        assert "unresolved" in result

    def test_repr_after_resolution(self) -> None:
        """Assert repr delegates to instance after resolution."""
        proxy = LazyProxy(_DummySettings)
        _ = proxy.value

        result = repr(proxy)

        assert "LazyProxy" not in result


class TestLazyProxyMockCompatibility:
    """Verify compatibility with mocker.patch.object (used in test fixtures)."""

    def test_patch_object_on_proxy(self, mocker) -> None:
        """Assert mocker.patch.object works on the proxy like a real object."""
        proxy = LazyProxy(_DummySettings)

        mocker.patch.object(proxy, "value", PATCHED_VALUE)

        assert proxy.value == PATCHED_VALUE

    def test_patch_object_restores_on_cleanup(self) -> None:
        """Assert mocker.patch.object properly restores after cleanup."""
        proxy = LazyProxy(_DummySettings)
        _ = proxy.value

        patcher = patch.object(proxy, "value", PATCHED_VALUE)
        patcher.start()
        assert proxy.value == PATCHED_VALUE

        patcher.stop()
        assert proxy.value == INITIAL_VALUE
