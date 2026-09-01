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

"""Shared helpers for Alembic multi-track CLIs under ``scripts/``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic.config import Config

if TYPE_CHECKING:
    import argparse

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INI = REPO_ROOT / "alembic.ini"


def list_track_names(ini_path: Path) -> tuple[str, ...]:
    """Return named Alembic configs listed in ``[alembic] databases``.

    :param ini_path: Path to ``alembic.ini``.
    :return: Track names in declaration order.
    :raises ValueError: If ``databases`` is missing or empty.
    """
    cfg = Config(str(ini_path))
    databases = cfg.get_main_option("databases") or ""
    names = tuple(part.strip() for part in databases.split(",") if part.strip())
    if not names:
        msg = f"{ini_path}: [alembic] databases is missing or empty"
        raise ValueError(msg)
    return names


def add_ini_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``--ini`` flag used by Alembic track CLIs.

    :param parser: Argument parser to extend.
    """
    parser.add_argument(
        "--ini",
        type=Path,
        default=DEFAULT_INI,
        help="path to alembic.ini (default: repo-root alembic.ini). "
        "Must be run from the repository root so relative script_location "
        "paths in the ini resolve correctly.",
    )
