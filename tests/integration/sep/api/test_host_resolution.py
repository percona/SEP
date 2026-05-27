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

"""Tests for ``app.sep.api.host_resolution``."""

from app.sep.api.host_resolution import (
    address_to_name_index,
    resolve_executor_name_by_address,
)


class TestAddressToNameIndex:
    """Tests for ``address_to_name_index``."""

    def test_inverts_pairs_into_address_keyed_dict(self) -> None:
        """Invert ``(name, address)`` pairs into an ``{address: name}`` index."""
        pairs = [("nomad-1", "10.0.0.1"), ("nomad-2", "10.0.0.2")]
        assert address_to_name_index(pairs) == {
            "10.0.0.1": "nomad-1",
            "10.0.0.2": "nomad-2",
        }

    def test_first_wins_on_duplicate_address(self) -> None:
        """Keep the first name encountered when two pairs share an address."""
        pairs = [
            ("nomad-primary", "10.0.0.1"),
            ("nomad-shadow", "10.0.0.1"),
        ]
        assert address_to_name_index(pairs) == {"10.0.0.1": "nomad-primary"}

    def test_returns_empty_for_empty_iterable(self) -> None:
        """Return an empty dict when no pairs are passed."""
        assert address_to_name_index([]) == {}

    def test_consumes_generator(self) -> None:
        """Accept a generator (single-pass iterable) without buffering it twice."""
        pairs = ((name, addr) for name, addr in [("a", "1"), ("b", "2")])
        assert address_to_name_index(pairs) == {"1": "a", "2": "b"}


class TestResolveExecutorNameByAddress:
    """Tests for ``resolve_executor_name_by_address``."""

    def test_returns_executor_name_when_address_matches(self) -> None:
        """Return the executor node name registered for the given address."""
        executor_hosts = {"nomad-1": "10.0.0.1", "nomad-2": "10.0.0.2"}
        assert resolve_executor_name_by_address("10.0.0.2", executor_hosts) == "nomad-2"

    def test_returns_none_when_address_not_registered(self) -> None:
        """Return ``None`` when no executor host has the given address."""
        executor_hosts = {"nomad-1": "10.0.0.1"}
        assert resolve_executor_name_by_address("10.0.0.99", executor_hosts) is None

    def test_returns_none_for_empty_executor_mapping(self) -> None:
        """Return ``None`` when the executor mapping is empty."""
        assert resolve_executor_name_by_address("10.0.0.1", {}) is None

    def test_returns_first_match_when_multiple_executors_share_address(self) -> None:
        """Return the first executor name in iteration order on duplicate addresses.

        Two Nomad clients can legitimately bind the same address (e.g. a
        compose-style lab where two agents share a host). The helper picks
        the first match in iteration order so the caller gets a stable
        choice rather than an exception.
        """
        executor_hosts = {
            "nomad-primary": "10.0.0.1",
            "nomad-shadow": "10.0.0.1",
        }
        assert (
            resolve_executor_name_by_address("10.0.0.1", executor_hosts)
            == "nomad-primary"
        )

    def test_handles_inventory_vs_executor_name_mismatch(self) -> None:
        """Resolve the executor name even when it differs from the inventory name.

        Reproduce SEP-1108: inventory records ``mvc-lab-maria1`` while the
        Nomad agent registers ``mvc-lab-db3``. Looking up by address must
        return the executor-keyed name expected by ``/connectivity-check/``.
        """
        executor_hosts = {"mvc-lab-db3": "192.168.1.10"}
        assert (
            resolve_executor_name_by_address("192.168.1.10", executor_hosts)
            == "mvc-lab-db3"
        )
