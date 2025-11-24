"""Tests for the MUM encryption helper."""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet

from app.sep.config import sep_settings
from app.sep.plugins.mum import security


@pytest.fixture(autouse=True)
def reset_cipher_cache():
    """Ensure cipher cache is cleared between tests."""
    security.reset_cipher_cache()
    yield
    security.reset_cipher_cache()


@pytest.fixture
def configured_secret(monkeypatch) -> str:
    """Configure a valid Fernet key on the global settings."""
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(sep_settings, "MUM_SECRET_KEY", key)
    security.reset_cipher_cache()
    return key


def test_encrypt_and_decrypt_roundtrip(configured_secret):
    """Encrypting a payload should allow lossless decryption."""
    secure_payload = security.encrypt_sensitive_config({"username": "user", "password": "pw"})

    assert security.is_secure_config(secure_payload)
    restored = security.decrypt_sensitive_config(secure_payload)
    assert restored == {"username": "user", "password": "pw"}


def test_serialize_sensitive_config_returns_json(configured_secret):
    """serialize_sensitive_config should emit valid JSON envelope."""
    blob = security.serialize_sensitive_config({"foo": "bar"})
    decoded = json.loads(blob)

    assert security.is_secure_config(decoded)
    assert security.decrypt_sensitive_config(decoded) == {"foo": "bar"}


def test_encrypt_sensitive_config_without_key(monkeypatch):
    """Encrypting without a configured key should fail fast."""
    monkeypatch.setattr(sep_settings, "MUM_SECRET_KEY", None)
    security.reset_cipher_cache()

    with pytest.raises(security.MUMSecurityError):
        security.serialize_sensitive_config({"foo": "bar"})
