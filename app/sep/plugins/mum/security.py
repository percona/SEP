"""Encryption helpers for the MUM plugin."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.sep.config import sep_settings

SECURE_FLAG = "__secure__"
PAYLOAD_FIELD = "payload"
VERSION_FIELD = "version"
CURRENT_VERSION = 1


class MUMSecurityError(RuntimeError):
    """Raised when the MUM plugin cannot secure sensitive data."""


@lru_cache(maxsize=1)
def _cipher(key: str) -> Fernet:
    """Cache Fernet cipher instances keyed by the configured secret."""
    return Fernet(key.encode("utf-8"))


def reset_cipher_cache() -> None:
    """Clear the cached Fernet cipher (useful for testing)."""
    _cipher.cache_clear()


def _get_cipher() -> Fernet:
    """Return a Fernet cipher configured with the MUM secret key."""
    key = sep_settings.MUM_SECRET_KEY
    if not key:
        raise MUMSecurityError("MUM_SECRET_KEY is not configured")
    try:
        return _cipher(key)
    except (ValueError, TypeError) as exc:
        raise MUMSecurityError("MUM_SECRET_KEY is invalid") from exc


def encrypt_sensitive_config(config: dict[str, Any]) -> dict[str, Any]:
    """Encrypt a config dict and wrap it in a secure envelope."""
    if not isinstance(config, dict):
        raise MUMSecurityError("Only dictionary payloads are supported")

    cipher = _get_cipher()
    plaintext = json.dumps(config, separators=(",", ":")).encode("utf-8")
    ciphertext = cipher.encrypt(plaintext).decode("utf-8")

    return {
        VERSION_FIELD: CURRENT_VERSION,
        SECURE_FLAG: True,
        PAYLOAD_FIELD: ciphertext,
    }


def serialize_sensitive_config(config: dict[str, Any]) -> str:
    """Return a JSON string containing the encrypted config envelope."""
    secure_payload = encrypt_sensitive_config(config)
    return json.dumps(secure_payload, separators=(",", ":"))


def is_secure_config(obj: Any) -> bool:
    """Return True when the provided object looks like a secure config."""
    return isinstance(obj, dict) and bool(obj.get(SECURE_FLAG)) and PAYLOAD_FIELD in obj


def decrypt_sensitive_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Decrypt a secure config payload."""
    if not is_secure_config(payload):
        raise MUMSecurityError("Payload is not marked as secure")

    ciphertext = payload.get(PAYLOAD_FIELD)
    if not isinstance(ciphertext, str):
        raise MUMSecurityError("Secure payload is missing ciphertext")

    cipher = _get_cipher()
    try:
        plaintext = cipher.decrypt(ciphertext.encode("utf-8"))
    except InvalidToken as exc:
        raise MUMSecurityError("Unable to decrypt secure payload") from exc

    try:
        return json.loads(plaintext.decode("utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise MUMSecurityError("Secure payload contained invalid JSON") from exc
