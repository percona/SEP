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

"""Define tests for the app.sep.config module."""

from app.sep.config import PMMSettings


def test_pmm_api_key_masked_in_repr():
    """Test that api_key is masked in repr output."""
    pmm = PMMSettings(api_key="my-pmm-api-key")
    assert "my-pmm-api-key" not in repr(pmm)


def test_pmm_api_key_accepts_secretstr():
    """Test that PMMSettings accepts SecretStr for api_key."""
    pmm = PMMSettings(api_key="test-key")
    assert pmm.api_key.get_secret_value() == "test-key"
