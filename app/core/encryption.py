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

"""Encrypt and decrypt values SEP stores at rest, keyed by ``ENCRYPTION_KEY``.

The ciphertext is Fernet: authenticated AES-128-CBC carrying its own version
marker, timestamp and HMAC, rendered as URL-safe base64 text that any ``str``
or JSON column stores unchanged. Encryption is **not** deterministic: each call
derives a fresh IV, so two encryptions of one plaintext differ and ciphertext
can never be compared for equality.

Use :func:`is_encrypted`, never a caught :class:`DecryptionError`, to decide
whether a stored value still needs encrypting.
"""

__all__ = ["DecryptionError", "decrypt", "encrypt", "is_encrypted"]

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

_FERNET_VERSION = 0x80
"""The first byte of every decoded Fernet token, which is its version marker."""

_MIN_TOKEN_BYTES = 73
"""The shortest decodable Fernet token: version, timestamp, IV, one block, HMAC.

CBC pads even an empty plaintext to a full 16-byte block, so no shorter value is
decryptable. Accepting one would make a migration *skip* a value it can never
decrypt, leaving it in the clear for good.
"""


class DecryptionError(ValueError):
    """Define exception raised when a value cannot be decrypted with the configured key."""


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Return the process-wide cipher built from ``settings.ENCRYPTION_KEY``.

    Cached so the key is resolved once per process; ``cache_clear()`` resets it.
    Deferred behind an accessor rather than built at module scope so importing
    this module resolves no settings.

    :return: The cached cipher.
    """
    # circular-import: app.core.config imports app.core.settings_override.models,
    # whose package __init__ imports cache, which imports app.core.encryption
    # (this module).
    from app.core.config import settings

    return Fernet(settings.ENCRYPTION_KEY.get_secret_value().encode())


def encrypt(value: str) -> str:
    """Return ``value`` encrypted as URL-safe base64 ciphertext text.

    :param value: The plaintext to encrypt.
    :return: The ciphertext, storable in any text or JSON column.
    """
    return _get_fernet().encrypt(value.encode()).decode("ascii")


def decrypt(value: str) -> str:
    """Return the plaintext behind ``value``.

    :param value: The ciphertext to decrypt.
    :return: The decrypted plaintext.
    :raises DecryptionError: If ``value`` is not ciphertext this key produced,
        which covers a legacy plaintext value, a corrupt one, and one encrypted
        under a different key alike. Use :func:`is_encrypted` to tell those
        apart; this exception does not.
    """
    try:
        # Encode before handing the token over: Fernet narrows a str with
        # ascii, and base64 turns that failure into a plain ValueError its
        # binascii.Error handler does not catch, so a non-ASCII stored value
        # would escape uncaught instead of as DecryptionError.
        return _get_fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError(
            "Value could not be decrypted: it is malformed, or was encrypted "
            "with a different ENCRYPTION_KEY."
        ) from exc


def is_encrypted(value: str) -> bool:
    """Return whether ``value`` is structurally a Fernet token.

    Reads the token's own version marker instead of attempting a decrypt, so a
    token written under a *different* key still reports ``True``. That is the
    property a migration needs: a caught :class:`DecryptionError` cannot
    separate "never encrypted" from "encrypted with a key this process does not
    hold", and encrypting the latter again destroys the only copy of its
    plaintext.

    :param value: The stored value to classify.
    :return: ``True`` when ``value`` is shaped like a Fernet token, ``False``
        for anything else, including input that is not valid base64 at all.
    """
    try:
        raw = base64.urlsafe_b64decode(value)
    except ValueError:
        return False
    return len(raw) >= _MIN_TOKEN_BYTES and raw[0] == _FERNET_VERSION
