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

"""Tests for the activation-list-driven form-backfill entry collector."""

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from app.sep.apps.alters.form_backfill import reconstruct_alters_form
from app.sep.apps.alters.models import AltersCreate
from app.sep.apps.archives.form_backfill import reconstruct_archives_form
from app.sep.apps.archives.models import ArchivesCreate
from app.sep.apps.backup_pg.form_backfill import reconstruct_backup_pg_form
from app.sep.apps.backup_pg.models import BackupPgForm
from app.sep.apps.checksums.form_backfill import reconstruct_checksums_form
from app.sep.apps.checksums.models import ChecksumsForm
from app.sep.apps.framework.form_backfill_registry import (
    collect_form_backfill_entries,
    FormBackfillEntry,
)
from app.sep.apps.mysql_backups.form_backfill import reconstruct_mysql_backups_form
from app.sep.apps.mysql_backups.forms import BackupCreate
from app.sep.apps.mysql_backups.restore.form_backfill import (
    reconstruct_mysql_restores_form,
)
from app.sep.apps.mysql_backups.restore.models import RestoreCreate
from app.sep.config import App, sep_settings

EXPECTED_DEFAULT_ENTRIES = [
    ("alters", "ALTERS", AltersCreate, reconstruct_alters_form),
    ("archives", "ARCHIVER", ArchivesCreate, reconstruct_archives_form),
    ("mysql_backups", "BACKUPS", BackupCreate, reconstruct_mysql_backups_form),
    (
        "mysql_backups/restore",
        "RESTORES",
        RestoreCreate,
        reconstruct_mysql_restores_form,
    ),
    ("checksums", "CHECKSUMS", ChecksumsForm, reconstruct_checksums_form),
    ("backup_pg", "BACKUP_PG", BackupPgForm, reconstruct_backup_pg_form),
]


def _fake_declaring_module(mocker: MockerFixture, declaration: object) -> MagicMock:
    """Return a module stand-in exporting ``declaration`` as its entry list."""
    module = mocker.MagicMock()
    module.FORM_BACKFILL_ENTRIES = declaration
    return module


def _patch_collector_import(mocker: MockerFixture, module: MagicMock) -> None:
    """Redirect only the collector's ``import_module`` to ``module``.

    ``build_app_registry`` resolves its own ``import_module`` binding in
    ``registry``, which stays unpatched, so the registry validating ``app_key``
    is built from genuine app packages while the collector reads the fake
    declaration.
    """
    mocker.patch(
        "app.sep.apps.framework.form_backfill_registry.import_module",
        return_value=module,
    )


def test_collects_every_declared_entry_from_the_default_activation():
    """Return one entry per declaring app, in activation order."""
    entries = collect_form_backfill_entries(sep_settings.APPS)

    assert [
        (entry.app_key, entry.owner, entry.create_model, entry.reconstructor)
        for entry in entries
    ] == EXPECTED_DEFAULT_ENTRIES


def test_skips_apps_without_a_declaration():
    """Ignore activation entries that export no ``FORM_BACKFILL_ENTRIES``."""
    assert collect_form_backfill_entries([App(module_name="report")]) == []


def test_applies_no_enabled_filter():
    """Collect a declaring app's entry even when its activation entry is disabled."""
    entries = collect_form_backfill_entries(
        [App(module_name="checksums", enabled=False)],
    )

    assert [entry.app_key for entry in entries] == ["checksums"]


def test_validates_app_key_against_a_registry_of_real_app_packages(
    mocker: MockerFixture,
):
    """Accept a fake declaration whose ``app_key`` names a genuinely activated app.

    This pins the two-binding split the fail-fast tests below depend on: were
    ``build_app_registry`` reading the patched binding too, the registry would be
    built from the stand-in module and ``"checksums"`` would resolve to nothing.
    """
    entry = FormBackfillEntry(
        app_key="checksums",
        owner="CHECKSUMS",
        create_model=ChecksumsForm,
        reconstructor=reconstruct_checksums_form,
    )
    _patch_collector_import(mocker, _fake_declaring_module(mocker, [entry]))

    assert collect_form_backfill_entries([App(module_name="checksums")]) == [entry]


def test_rejects_duplicate_app_key(mocker: MockerFixture):
    """Fail when two entries declare the same app key."""
    entry = FormBackfillEntry(
        app_key="checksums",
        owner="CHECKSUMS",
        create_model=ChecksumsForm,
        reconstructor=reconstruct_checksums_form,
    )
    _patch_collector_import(mocker, _fake_declaring_module(mocker, [entry, entry]))

    with pytest.raises(ValueError, match="declared by more than one"):
        collect_form_backfill_entries([App(module_name="checksums")])


def test_rejects_unknown_app_key(mocker: MockerFixture):
    """Fail when an entry names an app key absent from the registry."""
    entry = FormBackfillEntry(
        app_key="ghost",
        owner="CHECKSUMS",
        create_model=ChecksumsForm,
        reconstructor=reconstruct_checksums_form,
    )
    _patch_collector_import(mocker, _fake_declaring_module(mocker, [entry]))

    with pytest.raises(ValueError, match="unknown app key 'ghost'"):
        collect_form_backfill_entries([App(module_name="checksums")])


def test_rejects_non_list_declaration(mocker: MockerFixture):
    """Fail when ``FORM_BACKFILL_ENTRIES`` is not a list."""
    _patch_collector_import(mocker, _fake_declaring_module(mocker, "not-a-list"))

    with pytest.raises(TypeError, match="must be a list"):
        collect_form_backfill_entries([App(module_name="checksums")])


def test_rejects_non_entry_list_items(mocker: MockerFixture):
    """Fail when a declared list item is not a ``FormBackfillEntry``."""
    _patch_collector_import(mocker, _fake_declaring_module(mocker, ["not-an-entry"]))

    with pytest.raises(TypeError, match="FormBackfillEntry"):
        collect_form_backfill_entries([App(module_name="checksums")])
