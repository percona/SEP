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

"""Shared helpers for the snippet test suites.

Any suite that mutates a persisted snippet's metadata directly needs the same
two-step seed: write the metadata to the database, because the routes reload the row
by filename, and evict the derived reads the in-memory instance already cached. The
shape is stated here once for all of them.

The corpus-wide suites that read every builtin script also share one walk of the
snippets directory, so a file the application would ingest is never silently left
out of one check while another covers it.
"""

from functools import cached_property
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.sep.snippets.checksums import BUILTIN_CHECKSUM_MANIFEST, manifest_relative_path
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models.snippet import Snippet


def enumerate_snippets() -> tuple[str, ...]:
    """Collect every snippet filename the application would ingest.

    Walks the snippets directory as :func:`app.sep.snippets.celery.update_snippets`
    does, skipping the checksum manifest that shares it. The sync filter that
    function additionally applies is deliberately not mirrored: a file it would
    decline to ingest still has content an author can get wrong.

    :return: The snippet filenames, relative to the snippets directory, sorted.
    """
    names: list[str] = []
    for path in snippets_settings.SNIPPETS_DIR.rglob("*"):
        if not path.is_file():
            continue
        name = manifest_relative_path(path, snippets_settings.SNIPPETS_DIR)
        if name == BUILTIN_CHECKSUM_MANIFEST:
            continue
        names.append(name)
    return tuple(sorted(names))


SNIPPET_FILENAMES = enumerate_snippets()


def drop_cached_reads(snippet: Snippet) -> None:
    """Evict every ``cached_property`` value held on ``snippet``.

    A snippet's derived reads are ``cached_property`` values kept in the instance
    ``__dict__``, and a cache name does not always match the metadata key feeding it
    — ``parameters`` drives ``validated_parameters``. Clearing all of them spares
    callers from tracking which key drives which read.

    :param snippet: The snippet whose derived reads should be re-derived on next access.
    """
    for klass in type(snippet).__mro__:
        for name, attribute in vars(klass).items():
            if isinstance(attribute, cached_property):
                snippet.__dict__.pop(name, None)


async def persist_meta(
    session: AsyncSession, snippet: Snippet, updates: dict[str, Any]
) -> Snippet:
    """Merge ``updates`` into ``snippet.meta``, persist them, and drop stale reads.

    ``updates`` is applied as given, so a key whose value is ``None`` is written
    rather than skipped — that is the shape a valueless frontmatter line parses to,
    and the one a ``dict.get`` default cannot absorb.

    :param session: The session owning the snippet row.
    :param snippet: The snippet to update.
    :param updates: The metadata keys and values to write.
    :return: The same snippet, with its metadata persisted.
    """
    snippet.meta = {**snippet.meta, **updates}
    drop_cached_reads(snippet)
    await SnippetManager.save(session, snippet, flag_modified_fields=["meta"])
    return snippet
