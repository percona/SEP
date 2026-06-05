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

"""Tests for the app.sep.plugins.mysql_backups.models module."""

import pytest
from pydantic import ValidationError

from app.sep.plugins.mysql_backups.models import BackupConfigAll


class TestXtrabackupQuietField:
    """Tests for the ``xtrabackup_quiet`` field on ``BackupConfigAll``."""

    def test_defaults_to_false(self):
        """Field defaults to False; existing tasks are unaffected by the addition."""
        config = BackupConfigAll.model_validate({})
        assert config.xtrabackup_quiet is False

    def test_accepts_true(self):
        """Field accepts True via case-insensitive key validation."""
        config = BackupConfigAll.model_validate({"Xtrabackup_Quiet": True})
        assert config.xtrabackup_quiet is True

    def test_accepts_false_explicitly(self):
        """Explicit False round-trips correctly (not just the default)."""
        config = BackupConfigAll.model_validate({"XTRABACKUP_QUIET": False})
        assert config.xtrabackup_quiet is False

    def test_survives_config_all_round_trip(self):
        """True value persists when BackupConfigAll serialises and re-validates itself.

        Regression guard for the SEP-1239 pattern: ``BackupConfigAll`` uses
        ``extra='ignore'``, so any field missing from the class is silently
        dropped on re-validation.  The field must be declared on
        ``BackupConfigAll`` — not only on ``BackupCreate`` — or it vanishes
        from the persisted YAML config and the Nomad payload never sees it.
        """
        config = BackupConfigAll.model_validate({"XTRABACKUP_QUIET": True})
        serialised = {k.upper(): v for k, v in config.model_dump().items()}
        round_tripped = BackupConfigAll.model_validate(serialised)
        assert round_tripped.xtrabackup_quiet is True

    def test_none_raises_validation_error(self):
        """None is not a valid boolean; must raise ValidationError, not coerce to False.

        A ``null`` YAML value or an explicit ``None`` from the form layer
        must surface as a validation failure rather than silently becoming
        ``False``, which would mask a misconfigured task.
        """
        with pytest.raises(ValidationError):
            BackupConfigAll.model_validate({"XTRABACKUP_QUIET": None})


class TestUploadQuietField:
    """Tests for the ``upload_quiet`` field on ``BackupConfigAll``."""

    def test_defaults_to_false(self):
        """Field defaults to False; existing tasks are unaffected by the addition."""
        config = BackupConfigAll.model_validate({})
        assert config.upload_quiet is False

    def test_accepts_true(self):
        """Field accepts True via case-insensitive key validation."""
        config = BackupConfigAll.model_validate({"UPLOAD_QUIET": True})
        assert config.upload_quiet is True

    def test_accepts_false_explicitly(self):
        """Explicit False round-trips correctly (not just the default)."""
        config = BackupConfigAll.model_validate({"UPLOAD_QUIET": False})
        assert config.upload_quiet is False

    def test_survives_config_all_round_trip(self):
        """True value persists when BackupConfigAll serialises and re-validates itself.

        Regression guard for the SEP-1239 pattern: ``BackupConfigAll`` uses
        ``extra='ignore'``, so any field missing from the class is silently
        dropped on re-validation.  The field must be declared on
        ``BackupConfigAll`` — not only on ``BackupCreate`` — or it vanishes
        from the persisted YAML config and the Nomad payload never sees it.
        """
        config = BackupConfigAll.model_validate({"UPLOAD_QUIET": True})
        serialised = {k.upper(): v for k, v in config.model_dump().items()}
        round_tripped = BackupConfigAll.model_validate(serialised)
        assert round_tripped.upload_quiet is True

    def test_none_raises_validation_error(self):
        """None is not a valid boolean; must raise ValidationError, not coerce to False.

        A ``null`` YAML value or an explicit ``None`` from the form layer
        must surface as a validation failure rather than silently becoming
        ``False``, which would mask a misconfigured task.
        """
        with pytest.raises(ValidationError):
            BackupConfigAll.model_validate({"UPLOAD_QUIET": None})
