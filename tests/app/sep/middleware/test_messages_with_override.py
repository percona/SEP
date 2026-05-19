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

"""Backwards-compatibility tests for the ``MessagesSettings`` proxy conversion."""

import pytest
from fastapi.testclient import TestClient

from app.core.utils.lazy import _SENTINEL
from app.sep.main import sep_app
from app.sep.middleware.messages.config import messages_settings, MessagesSettings


def test_messages_settings_resolved_at_lifespan_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``messages_settings._resolve()`` fires during the SEP lifespan startup.

    ``MessagesSettings`` is now wrapped in :class:`OverridableSettingsProxy`,
    which defers validation to first attribute access. The SEP lifespan
    calls ``messages_settings._resolve()`` to restore the eager-validation
    semantics it had before the proxy conversion. Patching
    ``MessagesSettings.__init__`` to raise and entering the lifespan must
    surface the error during startup, not on first request.
    """
    # Drop the previously-resolved instance so ``_resolve`` re-invokes the
    # factory under the broken ``__init__`` instead of returning a cached value.
    object.__setattr__(messages_settings, "_instance", _SENTINEL)

    def _broken_init(self: MessagesSettings, *args: object, **kwargs: object) -> None:
        raise ValueError("intentionally invalid messages config")

    monkeypatch.setattr(MessagesSettings, "__init__", _broken_init)
    try:
        with (
            pytest.raises(ValueError, match="intentionally invalid messages config"),
            TestClient(sep_app),
        ):
            pass
    finally:
        # Restore the cached LazyProxy slot so subsequent tests reuse a valid
        # instance instead of re-running the (now-restored) ``__init__``.
        monkeypatch.undo()
        object.__setattr__(messages_settings, "_instance", _SENTINEL)
        messages_settings._resolve()
