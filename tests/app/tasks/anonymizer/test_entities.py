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
