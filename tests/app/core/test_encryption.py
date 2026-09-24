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
    _CIPHERTEXT_V1_PREFIX,
    _FERNET_VERSION,
    _get_fernet,
    _MIN_TOKEN_BYTES,
    decrypt,
    DecryptionError,
    encrypt,
    is_encrypted,
    is_stored_ciphertext,
    mark_ciphertext,
    marked_ciphertext,
)
from tests.app.encryption_fixtures import foreign_token

URLSAFE_B64_ALPHABET = frozenset(string.ascii_letters + string.digits + "-_=")
"""The character set ``base64.urlsafe_b64encode`` can emit, padding included."""


@pytest.fixture(autouse=True)
def _reset_fernet_cache() -> Iterator[None]:
    """Drop the cached Fernet around each test so a re-keyed setting takes effect."""
    _get_fernet.cache_clear()
    yield
    _get_fernet.cache_clear()


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


def test_is_encrypted_true_for_shortest_real_token():
    """Assert the shortest token this key can mint is not reported as plaintext.

    CBC pads even an empty plaintext to a full block, so ``encrypt("")`` sits
    exactly on the 73-byte floor. This pins that floor from above, where the
    undersized-shape test below pins it from below: raising it by one would make
    a migration re-encrypt a value that was already encrypted.
    """
    assert is_encrypted(encrypt("")) is True


def test_is_encrypted_false_for_undersized_token_shape():
    """Assert a value too short to be a Fernet token is reported as plaintext.

    Fernet's shortest token is 73 bytes, since CBC pads even an empty plaintext
    to a full block. Reporting a shorter value as encrypted would make a
    migration skip something it can never decrypt, leaving it in the clear for
    good.
    """
    undersized = base64.urlsafe_b64encode(bytes([_FERNET_VERSION]) + bytes(56))

    assert is_encrypted(undersized.decode("ascii")) is False


def test_is_encrypted_false_when_a_token_carries_a_non_base64_character():
    """Assert a stray space is rejected rather than silently discarded.

    ``base64.urlsafe_b64decode`` drops every character outside the alphabet
    before decoding, which makes the classification a question about whatever
    survives rather than about the value stored. Ordinary prose passes it often
    enough to matter: such a value is skipped by a migration and left in the
    clear, then reported as undecryptable ciphertext on every later read.
    """
    token = encrypt("hunter2")
    tampered = f"{token[:20]} {token[20:]}"

    assert is_encrypted(tampered) is False


def test_is_encrypted_false_for_a_block_misaligned_payload():
    """Assert a value the block framing rules out is reported as plaintext.

    A Fernet token is a 57-byte envelope around a whole number of cipher
    blocks, so a decoded length that is long enough and starts with the version
    marker can still be one no token could have.
    """
    misaligned = bytes([_FERNET_VERSION]) + b"\x00" * 80

    assert len(misaligned) > _MIN_TOKEN_BYTES
    assert is_encrypted(base64.urlsafe_b64encode(misaligned).decode("ascii")) is False


@pytest.mark.parametrize("length", [0, 1, 15, 16, 17, 200, 1000])
def test_is_encrypted_true_for_every_real_token_length(length: int):
    """Assert tightening the check still accepts every token this key mints.

    :param length: The plaintext length whose token is classified.
    """
    assert is_encrypted(encrypt("x" * length)) is True


@pytest.mark.parametrize(
    "value",
    ["!!not base64!!", "aGVsbG8", "héllo ünicode", "=" * 100],
)
def test_is_encrypted_never_raises(value: str):
    """Assert an undecodable stored value is reported, not raised on.

    :param value: The malformed value under test.
    """
    assert is_encrypted(value) is False


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


def test_mark_ciphertext_only_prefixes_the_token():
    """Assert marking prepends the marker and leaves the token byte-identical."""
    token = encrypt("hunter2")

    assert mark_ciphertext(token) == f"{_CIPHERTEXT_V1_PREFIX}{token}"


def test_marked_ciphertext_round_trips_a_marked_token():
    """Assert the envelope gives back the bare token, which the key still decrypts."""
    token = marked_ciphertext(mark_ciphertext(encrypt("hunter2")))

    assert token is not None
    assert decrypt(token) == "hunter2"


def test_the_marker_carries_a_character_outside_the_base64_alphabet():
    """Assert the marker cannot be read as base64, which is what makes it decisive.

    A marker drawn only from the base64url alphabet would leave
    :func:`is_encrypted`'s answer for a marked value depending on the token's
    length and padding, so the two discriminators could both claim one value.
    """
    assert not set(_CIPHERTEXT_V1_PREFIX) <= URLSAFE_B64_ALPHABET


def test_is_encrypted_false_for_a_marked_token():
    """Assert a marked value is invisible to the structural check.

    The property every marker-blind consumer depends on being told about: the
    side-car's freshness probe reads a marked row as carrying no ciphertext
    unless it tests the envelope first.
    """
    assert is_encrypted(mark_ciphertext(encrypt("hunter2"))) is False


def test_marked_ciphertext_none_for_a_legacy_token():
    """Assert an unmarked token written before the envelope is not claimed by it."""
    assert marked_ciphertext(encrypt("hunter2")) is None


def test_marked_ciphertext_none_for_a_plaintext_carrying_the_marker():
    """Assert the payload check refuses a prefix the writer never produced.

    A bare prefix test would read this legacy plaintext as ciphertext, leave it
    in the clear through the migration, and fail every later read of it.
    """
    assert marked_ciphertext(f"{_CIPHERTEXT_V1_PREFIX}operator-secret") is None


def test_marked_ciphertext_none_for_a_marker_over_a_corrupt_token():
    """Assert a truncated payload falls back to plaintext rather than raising.

    Matches what the unmarked path already does with a corrupt token, so the
    two envelopes fail identically on a corrupted value.
    """
    truncated = encrypt("hunter2")[:40]

    assert marked_ciphertext(f"{_CIPHERTEXT_V1_PREFIX}{truncated}") is None


def test_marked_ciphertext_none_for_an_unmarked_plaintext():
    """Assert an ordinary stored plaintext is never claimed by the envelope."""
    assert marked_ciphertext("hunter2") is None


def test_marked_ciphertext_accepts_a_foreign_token_behind_the_marker():
    """Assert the envelope classifies by shape, not by whether this key can read it.

    The property :func:`~app.core.settings_override.secret_storage.unmark_secret_leaves`
    relies on: a marked token minted under a rotated-away key must still be
    recognised, so the rollback strips its marker instead of skipping the row.
    """
    token = marked_ciphertext(mark_ciphertext(foreign_token()))

    assert token is not None
    with pytest.raises(DecryptionError):
        decrypt(token)


def test_is_stored_ciphertext_accepts_a_marked_token():
    """Assert the envelope half of the discriminator claims a marked value."""
    assert is_stored_ciphertext(mark_ciphertext(encrypt("hunter2"))) is True


def test_is_stored_ciphertext_accepts_a_legacy_unmarked_token():
    """Assert the structural fallback still claims a row written before the envelope.

    The half that keeps every pre-envelope deployment readable: nothing
    re-marks those rows, so a discriminator that dropped the fallback would
    report a store full of them as holding no ciphertext.
    """
    assert is_stored_ciphertext(encrypt("hunter2")) is True


def test_is_stored_ciphertext_rejects_a_plaintext():
    """Assert an ordinary stored plaintext is claimed by neither half."""
    assert is_stored_ciphertext("hunter2") is False


def test_is_stored_ciphertext_rejects_a_marker_over_a_corrupt_token():
    """Assert a marked value whose payload is damaged is not claimed as ciphertext.

    Neither half accepts it: the envelope refuses the payload, and the marker's
    ``.`` puts the whole string outside the structural check's alphabet. The
    rollback therefore leaves it alone rather than stripping a marker off
    something it cannot vouch for.
    """
    truncated = encrypt("hunter2")[:40]

    assert is_stored_ciphertext(f"{_CIPHERTEXT_V1_PREFIX}{truncated}") is False
