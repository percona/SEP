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

"""Share what every at-rest-encryption test suite needs to read a stored value.

The two fixtures exercise the seam between what
:func:`~app.core.encryption.is_encrypted` can tell structurally and what only a
decrypt attempt could: a plaintext it accepts, and ciphertext it accepts that
the configured key cannot read. Every consumer of the encryption primitive has
the same pair of cases, so they live here rather than being copied per suite.

:func:`stored_plaintext` beside them reads a leaf back out of storage without the
calling test having to know which envelope carried it — the marked one
:mod:`app.core.settings_override.secret_storage` writes today, or the bare token
a row predating it still holds.
:func:`~app.core.encryption.is_stored_ciphertext` is re-exported here rather than
reimplemented, so a suite importing it gets the production discriminator and not
a test-local copy that could disagree with it.
"""

__all__ = [
    "FERNET_SHAPED_PLAINTEXT",
    "foreign_token",
    "is_stored_ciphertext",
    "stored_plaintext",
]

import base64

from cryptography.fernet import Fernet

from app.core.encryption import decrypt, is_stored_ciphertext, marked_ciphertext

#: A plaintext credential ``is_encrypted`` misreads as a Fernet token, because it
#: satisfies every structural test one can pass without being decryptable: the
#: base64url alphabet, the version marker, and a decoded length matching Fernet's
#: 57-byte envelope around whole cipher blocks.
#:
#: Derived rather than spelled out as a literal. The structural test is allowed
#: to get stricter (it did, once a lenient decode was found to admit ordinary
#: prose) and a hardcoded string silently stops exercising the misreading when
#: that happens, turning the limitation these tests pin into a passing no-op.
#: Every test using it asserts the misreading first, so a value this stops
#: fooling fails loudly here rather than going quiet.
FERNET_SHAPED_PLAINTEXT = base64.urlsafe_b64encode(bytes([0x80]) + bytes(72)).decode(
    "ascii"
)


def foreign_token(value: str = "written under another key") -> str:
    """Return ciphertext minted with a key the configured one cannot decrypt.

    :param value: The plaintext to encrypt with the foreign key.
    :return: The foreign Fernet token.
    """
    return Fernet(Fernet.generate_key()).encrypt(value.encode()).decode("ascii")


def stored_plaintext(value: str) -> str:
    """Return the plaintext behind a stored leaf, marked or legacy-unmarked.

    Shared rather than spelled out per assertion because a stored leaf's
    envelope is not the assertion's subject: a test pinning *what* was stored
    should not also have to decide *which* envelope carried it, and one that
    hardcodes a bare :func:`~app.core.encryption.decrypt` stops working the
    moment the writer starts marking.

    :param value: The leaf as the column holds it.
    :return: The decrypted plaintext.
    :raises DecryptionError: If the leaf is ciphertext the configured
        ``ENCRYPTION_KEY`` cannot decrypt.
    """
    return decrypt(marked_ciphertext(value) or value)
