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

"""Define tests for the app.sep.models module."""

import pytest
from pydantic import ValidationError

from app.sep.models import AppLifecycleEnum, AppState, AppStateBase, AppStateWrite


class TestAppStateModel:
    """Test suite for the AppState model and its companions."""

    def test_base_lifecycle_state_defaults_to_enabled(self):
        """The shared base column-default for ``lifecycle_state`` is ``ENABLED``."""
        assert (
            AppStateBase(app_key="snippets").lifecycle_state is AppLifecycleEnum.ENABLED
        )

    def test_base_requires_app_key(self):
        """``app_key`` has no default — omitting it fails validation."""
        with pytest.raises(ValidationError):
            AppStateBase()

    def test_base_rejects_empty_app_key(self):
        """``app_key`` is a ``NonEmptyStr`` — an empty string is rejected."""
        with pytest.raises(ValidationError):
            AppStateBase(app_key="")

    def test_table_model_lifecycle_state_defaults_to_enabled(self):
        """The table model inherits the ``lifecycle_state=ENABLED`` column default."""
        assert AppState(app_key="snippets").lifecycle_state is AppLifecycleEnum.ENABLED

    def test_write_model_requires_lifecycle_state(self):
        """The write payload requires ``lifecycle_state`` — it has no default."""
        with pytest.raises(ValidationError):
            AppStateWrite()

    def test_write_model_rejects_unknown_lifecycle_state(self):
        """The write payload rejects a value outside ``AppLifecycleEnum``."""
        with pytest.raises(ValidationError):
            AppStateWrite(lifecycle_state="BOGUS")
