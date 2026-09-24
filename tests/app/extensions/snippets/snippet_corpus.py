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

"""One walk of the snippets directory for every corpus-wide suite.

The suites that hold all builtin scripts to a rule — front-matter authoring, the
pipefail guard contract — share this enumeration, so a file the application would
ingest is never silently left out of one check while another covers it.
"""

from app.extensions.snippets.checksums import (
    BUILTIN_CHECKSUM_MANIFEST,
    manifest_relative_path,
)
from app.extensions.snippets.config import snippets_settings


def enumerate_snippets() -> tuple[str, ...]:
    """Collect every snippet filename the application would ingest.

    Walks the snippets directory as :func:`app.extensions.snippets.celery.update_snippets`
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
SHELL_SNIPPET_FILENAMES = tuple(
    name for name in SNIPPET_FILENAMES if name.endswith(".sh")
)
