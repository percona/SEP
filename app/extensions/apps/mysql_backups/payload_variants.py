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

"""Name the ``xtrabackup_payload`` variant carrying a given upload selection.

The rule is read by both the dispatcher and the generator, which must never
disagree: a divergence dispatches a payload that does not exist. It lives here so
neither side owns a second copy, and the generator's ``--check`` mode holds the
written files to it.

The module is deliberately stdlib-only: the generator runs as a pre-commit hook
and loads this file directly, without importing the ``mysql_backups`` package,
whose ``__init__`` builds the FastAPI app.
"""

import itertools

__all__ = ["CANONICAL_PAYLOAD_NAME", "PROVIDERS", "selections", "variant_name"]

#: Upload providers in the order variant filenames spell them. The order is part
#: of the filenames, so it must stay stable and match ``UploadProvider``.
PROVIDERS = ("rsync", "s3", "gsutil")

#: The all-providers variant, which is the complete hand-edited source rather
#: than a generated file.
CANONICAL_PAYLOAD_NAME = "xtrabackup_payload"

#: The stem and suffix every variant filename shares with the canonical payload,
#: so a rename of the canonical carries the whole family with it.
_STEM, _SUFFIX = CANONICAL_PAYLOAD_NAME.split("_", 1)


def selections() -> list[tuple[str, ...]]:
    """Return every upload selection, from the empty set to all providers.

    Owned here rather than by the generator because the dispatcher, the generator,
    and the tests must all enumerate the same 2**n selections.

    :return: One tuple per selection, smallest first, each in :data:`PROVIDERS`
        order.
    """
    return [
        combo
        for size in range(len(PROVIDERS) + 1)
        for combo in itertools.combinations(PROVIDERS, size)
    ]


def variant_name(providers: tuple[str, ...]) -> str:
    """Return the payload filename carrying exactly ``providers``.

    Every name ends in ``_payload`` so the ``check-nomad-payload-size`` hook's file
    pattern matches the variants as well as the canonical payload.

    :param providers: The providers the variant carries, in :data:`PROVIDERS` order.
    :return: The variant's filename, beside the canonical payload.
    """
    if len(providers) == len(PROVIDERS):
        return CANONICAL_PAYLOAD_NAME
    if not providers:
        return f"{_STEM}_noupload_{_SUFFIX}"
    return f"{_STEM}_{'_'.join(providers)}_{_SUFFIX}"
