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

"""Define tests for the app.tasks.anonymizer.entities module."""

import pytest

from app.tasks.anonymizer.entities import PIIEntity


@pytest.mark.parametrize(
    "original_entities",
    [
        set(),
        {PIIEntity.EMAIL_ADDRESS},
        {
            PIIEntity.CREDIT_CARD,
            PIIEntity.IP_ADDRESS,
            PIIEntity.PERSON,
        },
        set(PIIEntity),
        [PIIEntity.CREDIT_CARD, PIIEntity.EMAIL_ADDRESS, PIIEntity.CREDIT_CARD],
    ],
)
def test_encode_decode_round_trip(original_entities):
    """Test that encode then decode returns the original entities."""
    encoded = PIIEntity.encode_selection(original_entities)
    decoded = PIIEntity.decode_selection(encoded)
    assert set(decoded) == set(original_entities)
