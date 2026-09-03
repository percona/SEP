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

"""Define tests for the app.core.encryption module."""

import base64
import json
import string
from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from app.core.config import settings
from app.core.encryption import (
    _FERNET_VERSION,
    _get_fernet,
    decrypt,
    DecryptionError,
    encrypt,
    is_encrypted,
)

URLSAFE_B64_ALPHABET = frozenset(string.ascii_letters + string.digits + "-_=")
"""The character set ``base64.urlsafe_b64encode`` can emit, padding included."""


@pytest.fixture(autouse=True)
def _reset_fernet_cache() -> Iterator[None]:
    """Drop the cached Fernet around each test so a re-keyed setting takes effect."""
    _get_fernet.cache_clear()
    yield
    _get_fernet.cache_clear()


def foreign_token(value: str = "written under another key") -> str:
    """Return ciphertext minted with a key the configured one cannot decrypt.

    :param value: The plaintext to encrypt with the foreign key.
    :return: The foreign Fernet token.
    """
    return Fernet(Fernet.generate_key()).encrypt(value.encode()).decode("ascii")


def test_round_trip():
    """Assert a secret survives an encrypt/decrypt round trip unchanged."""
    assert decrypt(encrypt("hunter2")) == "hunter2"


def test_round_trip_unicode():
    """Assert non-ASCII plaintext round-trips through UTF-8 unchanged."""
    assert decrypt(encrypt("héllo ünicode")) == "héllo ünicode"


def test_round_trip_empty_string():
    """Assert an empty secret is a value rather than an error."""
    assert decrypt(encrypt("")) == ""


def test_ciphertext_is_ascii_json_safe():
    """Assert the ciphertext is URL-safe base64 text that survives a JSON round trip."""
    token = encrypt("hunter2")

    assert isinstance(token, str)
    assert set(token)
    assert set(token) <= URLSAFE_B64_ALPHABET
    assert json.loads(json.dumps(token)) == token


def test_ciphertext_differs_from_plaintext():
    """Assert the plaintext does not appear inside the ciphertext."""
    token = encrypt("hunter2")

    assert token
    assert "hunter2" not in token


def test_encryption_is_not_deterministic():
    """Assert two encryptions of one plaintext differ, so ciphertext cannot be compared."""
    assert encrypt("hunter2") != encrypt("hunter2")


def test_wrong_key_raises():
    """Assert ciphertext from a different key is refused rather than mis-decrypted."""
    with pytest.raises(DecryptionError):
        decrypt(foreign_token())


def test_malformed_ciphertext_raises():
    """Assert a value that is not a Fernet token at all is refused."""
    with pytest.raises(DecryptionError):
        decrypt("not-ciphertext")


@pytest.mark.parametrize(
    "value",
    ["a-legacy-plaintext-value", "héllo ünicode", "", '{"a": 1}'],
    ids=["ascii", "non-ascii", "empty", "json"],
)
def test_plaintext_value_raises(value: str):
    """Assert a legacy plaintext value cannot be decrypted, whatever it holds.

    A migration catches :class:`DecryptionError` alone, so any other family
    escaping here aborts the run on the first row that carries it.

    :param value: The unencrypted stored value under test.
    """
    with pytest.raises(DecryptionError):
        decrypt(value)


def test_decryption_error_is_value_error():
    """Assert the raised error is a ``ValueError`` chained to the underlying token error."""
    assert issubclass(DecryptionError, ValueError)

    with pytest.raises(DecryptionError) as excinfo:
        decrypt("not-ciphertext")

    assert isinstance(excinfo.value.__cause__, InvalidToken)


def test_decryption_error_has_message():
    """Assert the raised error carries a message, which bare ``InvalidToken`` does not."""
    with pytest.raises(DecryptionError) as excinfo:
        decrypt("not-ciphertext")

    assert str(excinfo.value)


def test_is_encrypted_true_for_own_ciphertext():
    """Assert a token minted with the configured key reports as encrypted."""
    assert is_encrypted(encrypt("hunter2")) is True


def test_is_encrypted_true_for_foreign_ciphertext():
    """Assert a token minted with another key reports as encrypted, unlike ``decrypt``.

    A migration must branch on this rather than on a caught
    :class:`DecryptionError`: re-encrypting an undecryptable token destroys the
    only copy of its plaintext.
    """
    token = foreign_token()

    assert is_encrypted(token) is True
    with pytest.raises(DecryptionError):
        decrypt(token)


@pytest.mark.parametrize(
    "value",
    ["hunter2", "", "aGVsbG8=", '{"a": 1}', "https://example.com/path"],
)
def test_is_encrypted_false_for_plaintext(value: str):
    """Assert a value that was never encrypted reports as plaintext.

    :param value: The unencrypted value under test.
    """
    assert is_encrypted(value) is False


def test_is_encrypted_false_for_undersized_token_shape():
    """Assert a value too short to be a Fernet token is reported as plaintext.

    Fernet's shortest token is 73 bytes, since CBC pads even an empty plaintext
    to a full block. Reporting a shorter value as encrypted would make a
    migration skip something it can never decrypt, leaving it in the clear for
    good.
    """
    undersized = base64.urlsafe_b64encode(bytes([_FERNET_VERSION]) + bytes(56))

    assert is_encrypted(undersized.decode("ascii")) is False


@pytest.mark.parametrize(
    "value",
    ["!!not base64!!", "aGVsbG8", "héllo ünicode", "=" * 100],
)
def test_is_encrypted_never_raises(value: str):
    """Assert an undecodable stored value is reported, not raised on.

    :param value: The malformed value under test.
    """
    assert is_encrypted(value) is False


def test_unset_key_raises(monkeypatch: pytest.MonkeyPatch):
    """Refuse to build a cipher when the key was patched away after construction.

    :param monkeypatch: The settings patcher.
    """
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", None)

    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        encrypt("hunter2")


def test_fernet_is_cached(monkeypatch: pytest.MonkeyPatch):
    """Assert the Fernet is built once per process and rebuilt after ``cache_clear``.

    :param monkeypatch: The settings patcher.
    """
    assert _get_fernet() is _get_fernet()

    original = settings.ENCRYPTION_KEY.get_secret_value()
    rotated = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", SecretStr(rotated))

    assert Fernet(original).decrypt(encrypt("hunter2")) == b"hunter2"

    _get_fernet.cache_clear()

    assert Fernet(rotated).decrypt(encrypt("hunter2")) == b"hunter2"
