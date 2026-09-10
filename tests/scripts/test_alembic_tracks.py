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

"""Tests for ``scripts/alembic_tracks.py`` helpers."""

from __future__ import annotations

import argparse

import pytest

from scripts.alembic_tracks import add_ini_argument, DEFAULT_INI, list_track_names
from tests.scripts.alembic_tree import write_ini


def test_discovers_tracks_from_databases_key(tmp_path):
    """Discover track names from ``[alembic] databases``, not hard-coded lists."""
    ini_path = write_ini(
        tmp_path,
        databases="widget, gadget",
        sections={"widget": {}, "gadget": {}},
    )

    assert list_track_names(ini_path) == ("widget", "gadget")


def test_rejects_databases_with_no_track_names(tmp_path):
    """Raise when ``databases`` parses to an empty track list."""
    ini_path = write_ini(tmp_path, databases=",", sections={})

    with pytest.raises(ValueError, match="missing or empty"):
        list_track_names(ini_path)


def test_add_ini_argument_defaults_to_repo_alembic_ini():
    """Register ``--ini`` with the repo-root ``alembic.ini`` as the default."""
    parser = argparse.ArgumentParser()
    add_ini_argument(parser)
    args = parser.parse_args([])

    assert args.ini == DEFAULT_INI


def test_add_ini_argument_accepts_override(tmp_path):
    """Honor an explicit ``--ini`` path."""
    ini_path = tmp_path / "custom.ini"
    parser = argparse.ArgumentParser()
    add_ini_argument(parser)
    args = parser.parse_args(["--ini", str(ini_path)])

    assert args.ini == ini_path
