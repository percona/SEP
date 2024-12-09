"""Define tests for the app.core.security module."""

from app.core.security import crypto_serializer, crypto_timestamp_serializer


def test_crypto_serializer_basic():
    """Test basic serialization and deserialization."""
    payload = {"user_id": 123, "email": "test@example.com"}
    token = crypto_serializer.dumps(payload)
    decoded_payload = crypto_serializer.loads(token)
    assert decoded_payload == payload


def test_crypto_timestamp_serializer_basic():
    """Test basic serialization and deserialization with timestamp."""
    payload = {"user_id": 456, "email": "time@example.com"}
    token = crypto_timestamp_serializer.dumps(payload)
    decoded_payload = crypto_timestamp_serializer.loads(token)
    assert decoded_payload == payload
