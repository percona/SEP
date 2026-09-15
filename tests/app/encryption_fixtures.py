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

"""Share the two fixtures every at-rest-encryption test suite needs.

Both exist to exercise the seam between what
:func:`~app.core.encryption.is_encrypted` can tell structurally and what only a
decrypt attempt could: a plaintext it accepts, and ciphertext it accepts that
the configured key cannot read. Every consumer of the encryption primitive has
the same pair of cases, so they live here rather than being copied per suite.
"""

__all__ = ["FERNET_SHAPED_PLAINTEXT", "foreign_token"]

import base64

from cryptography.fernet import Fernet

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
