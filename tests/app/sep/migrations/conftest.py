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

"""Define the Alembic locations and revision ids the migration tests share."""

from __future__ import annotations

import importlib.util
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

from tests.app.alembic_paths import REPO_ROOT

# The create_alert_backup_table revision: the head of the alerts branch, the
# app the PMM-embedded side-car's allow-list strip removes.
ALERTS_HEAD = "d21ad387df7a"
# A revision id no branch in the tree defines, standing in for version skew.
UNKNOWN_REVISION = "deadbeef1234"

MINIMAL_REVISION = """\
revision = "{revision}"
down_revision = None
branch_labels = ({branch!r},)
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
"""


def write_revision(versions_dir: Path, revision: str, branch: str) -> None:
    """Write a no-op Alembic revision script under ``versions_dir``.

    :param versions_dir: Directory that should hold the revision script.
    :param revision: Alembic revision id embedded in the script.
    :param branch: Branch label recorded on the revision.
    """
    versions_dir.mkdir(parents=True, exist_ok=True)
    (versions_dir / f"{revision}_noop.py").write_text(
        MINIMAL_REVISION.format(revision=revision, branch=branch),
        encoding="utf-8",
    )


def load_sync_alembic_version_locations() -> ModuleType:
    """Load ``scripts/sync_alembic_version_locations.py`` as a module.

    :return: The loaded sync script module.
    """
    script_path = REPO_ROOT / "scripts" / "sync_alembic_version_locations.py"
    spec = importlib.util.spec_from_file_location(
        "sync_alembic_version_locations", script_path
    )
    assert spec is not None, f"cannot load {script_path}"
    assert spec.loader is not None, f"cannot load {script_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["sync_alembic_version_locations"] = module
    spec.loader.exec_module(module)
    return module
