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

"""Define the constants the artifact-download surface is built from.

Houses the itsdangerous salt every artifact-download signer and verifier shares,
so tokens validate under one namespace, plus the base-dir declarations that are
not owned by any activatable app.
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

from app.sep.snippets.config import snippets_settings
from app.sep.snippets.constants import ARTIFACT_TYPE_SNIPPET

__all__ = ["ARTIFACT_DOWNLOAD_SALT", "STATIC_ARTIFACT_BASE_DIRS"]

ARTIFACT_DOWNLOAD_SALT = "artifact-download"

#: Artifact base dirs seeding the download map. Not owned by a ``SEP.APPS`` app,
#: so they are not registry-derived; ``collect_base_dirs`` seeds them ahead of
#: the per-app declarations. The snippet directory is declared here because
#: snippet execution is library-owned: signed snippet-download URLs are built
#: through ``app.sep.snippets.script_source`` whether or not the snippets app is
#: activated, so the type they name must resolve on the same terms. Frozen so
#: ``collect_base_dirs`` must copy before overlaying the per-app declarations,
#: rather than leaking one image's activation set into the shared constant.
STATIC_ARTIFACT_BASE_DIRS: Mapping[str, Callable[[], Path]] = MappingProxyType(
    {ARTIFACT_TYPE_SNIPPET: lambda: snippets_settings.SNIPPETS_DIR}
)
