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

"""Shared builders for synthetic Alembic revision trees in script tests."""

from __future__ import annotations

import shutil
from pathlib import Path

from tests.scripts import PROJECT_ROOT

MAKO_TEMPLATE = PROJECT_ROOT / "app" / "tasks" / "migrations" / "script.py.mako"

_REVISION_TEMPLATE = """\
revision = {revision!r}
down_revision = {down_revision!r}
branch_labels = {branch_labels!r}
depends_on = None

def upgrade():
    pass

def downgrade():
    pass
"""


def write_revision(
    versions_dir: Path,
    revision: str,
    down_revision: str | tuple[str, ...] | None,
    *,
    branch_labels: str | tuple[str, ...] | None = None,
) -> None:
    """Write a minimal Alembic revision module.

    :param versions_dir: Directory that holds revision modules.
    :param revision: Revision id.
    :param down_revision: Parent revision id(s), or ``None`` for a root.
    :param branch_labels: Optional branch label(s) for this revision.
    """
    versions_dir.mkdir(parents=True, exist_ok=True)
    (versions_dir / f"{revision}.py").write_text(
        _REVISION_TEMPLATE.format(
            revision=revision,
            down_revision=down_revision,
            branch_labels=branch_labels,
        ),
        encoding="utf-8",
    )


def write_ini(
    tmp_path: Path,
    *,
    databases: str,
    sections: dict[str, dict[str, str]],
) -> Path:
    """Write a minimal ``alembic.ini`` for synthetic trees.

    :param tmp_path: Pytest temporary directory.
    :param databases: Value for ``[alembic] databases``.
    :param sections: Named section options keyed by section name.
    :return: Path to the written ini file.
    """
    lines = [
        "[alembic]",
        f"databases = {databases}",
        "",
        "[DEFAULT]",
        "path_separator = :",
        "version_path_separator = :",
        "",
    ]
    for name, options in sections.items():
        lines.append(f"[{name}]")
        for key, value in options.items():
            lines.append(f"{key} = {value}")
        lines.append("")
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text("\n".join(lines), encoding="utf-8")
    return ini_path


def dummy_script_location(tmp_path: Path, name: str = "migrations") -> Path:
    """Create a ``script_location`` directory with an empty ``env.py``.

    Sufficient for read-only revision-map inspection (no merge / revision
    generation).

    :param tmp_path: Pytest temporary directory.
    :param name: Directory name under ``tmp_path``.
    :return: The script location path.
    """
    script_location = tmp_path / name
    script_location.mkdir(parents=True, exist_ok=True)
    (script_location / "env.py").write_text("", encoding="utf-8")
    return script_location


def script_location_with_mako(tmp_path: Path, name: str = "migrations") -> Path:
    """Create a ``script_location`` with ``env.py`` and ``script.py.mako``.

    Required for Alembic's merge/revision file generation. Paths are resolved
    so ``version_locations`` comparisons succeed on platforms that symlink
    temporary directories (macOS ``/var`` → ``/private/var``).

    :param tmp_path: Pytest temporary directory.
    :param name: Directory name under ``tmp_path``.
    :return: The resolved script location path.
    """
    script_location = (tmp_path / name).resolve()
    script_location.mkdir(parents=True, exist_ok=True)
    (script_location / "env.py").write_text("", encoding="utf-8")
    shutil.copy(MAKO_TEMPLATE, script_location / "script.py.mako")
    return script_location
