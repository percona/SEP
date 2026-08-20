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

"""Filter ``alembic_version_sep`` rows whose migration scripts are not loaded.

Kept in a separate module (not ``env.py``) for the same reason as
``_discovery.py``: importing ``env.py`` runs migrations as a side effect, so
helpers that want unit tests live here. Unlike ``_discovery.py``'s helpers,
which run standalone, ``skip_unresolvable_heads`` needs a live
``MigrationContext`` and so is called after ``context.configure(...)`` rather
than at import time.

Each app that owns migrations is an independent branch rooted at ``base`` and
recorded in the shared ``alembic_version_sep`` table. An image that strips an
app removes its ``versions/`` directory; Alembic skips the absent
``version_locations`` entry but still has to resolve the recorded revision, and
one unresolvable row makes every upgrade on the track fail. Dropping such rows
from the heads Alembic is handed — while leaving them in the table — lets the
remaining branches migrate and lets a returning app resume from its preserved
revision instead of re-running its branch from ``base``.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from alembic.script.revision import ResolutionError

if TYPE_CHECKING:
    from alembic.runtime.environment import EnvironmentContext
    from alembic.script import ScriptDirectory

logger = logging.getLogger(__name__)


def partition_heads(
    script: "ScriptDirectory", heads: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split recorded heads by whether the loaded revision map resolves them.

    :param script: The Alembic script directory holding the revision map.
    :param heads: Revision ids read from the version table.
    :return: A tuple of (resolvable, unresolvable) revision ids, each in the
        order they appeared in ``heads``.
    """
    resolvable: list[str] = []
    unresolvable: list[str] = []
    for revision in heads:
        try:
            script.revision_map.get_revision(revision)
        except ResolutionError:
            unresolvable.append(revision)
        else:
            resolvable.append(revision)
    return tuple(resolvable), tuple(unresolvable)


def empty_version_locations(script: "ScriptDirectory") -> tuple[str, ...]:
    """Return configured ``version_locations`` entries that contribute no revisions.

    A location contributes no revisions when it is absent from disk or present
    but contains no migration scripts the loaded revision map resolved. Both
    conditions are evidence of a stripped (or scaffolded-but-empty) app and
    license skipping unresolvable heads.

    :param script: The Alembic script directory holding the configured paths
        and the loaded revision map.
    :return: Each configured location that contributed no revisions, in
        configuration order.
    """
    locations = script.version_locations or ()
    if not locations:
        return ()
    populated = {str(Path(rev.path).parent) for rev in script.walk_revisions()}
    return tuple(
        str(location)
        for location in locations
        if str(Path(location)) not in populated
    )


def skip_unresolvable_heads(env_context: "EnvironmentContext") -> None:
    """Make the migration context ignore heads whose migration scripts are gone.

    Wrap the context's ``get_current_heads`` so both the migrations function and
    the ``HeadMaintainer`` built alongside it see the same filtered set. Rows for
    the dropped revisions stay in the version table: Alembic only ever targets a
    specific ``version_num`` when it writes.

    Fail-closed: heads are only dropped when a configured ``version_locations``
    entry contributes no resolvable revisions — absent from disk or present and
    empty — which is what a stripped app looks like. With every location present
    and populated the evidence is absent — the cause may be version skew, a
    squashed revision, or an entry pruned from ``version_locations`` for an app
    that is gone — so the heads pass through unfiltered and Alembic raises as it
    does today.

    Offline (``--sql``) mode needs no hook: there ``get_current_heads`` returns
    the ``starting_rev`` argument instead of reading the version table.

    Call after ``context.configure(...)`` and before ``context.run_migrations()``.

    :param env_context: The Alembic environment context from ``env.py``.
    """
    migration_context = env_context.get_context()
    script = env_context.script
    read_heads = migration_context.get_current_heads

    def get_current_heads() -> tuple[str, ...]:
        heads = read_heads()
        resolvable, unresolvable = partition_heads(script, heads)
        if not unresolvable:
            return heads

        empty = empty_version_locations(script)
        if not empty:
            logger.error(
                "%d revision(s) recorded in %s do not resolve (%s) while every "
                "configured version_locations entry is present on disk and "
                "contributes at least one revision. Likely causes: version skew, "
                "a squashed revision, or a version_locations entry that was "
                "pruned or went stale for an app that is no longer installed. "
                "They are left in place for Alembic to reject.",
                len(unresolvable),
                migration_context.version_table,
                ", ".join(unresolvable),
            )
            return heads

        logger.warning(
            "Skipping %d revision(s) recorded in %s with no migration script: "
            "%s. Configured version_locations that contributed no revisions: %s.",
            len(unresolvable),
            migration_context.version_table,
            ", ".join(unresolvable),
            ", ".join(empty),
        )
        return resolvable

    migration_context.get_current_heads = get_current_heads
