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

"""Tests for the HOT-classification registry."""

from pydantic import BaseModel

from app.core.settings_override.registry import (
    hot_field_names,
    is_hot_reloadable,
    nested_overridable_field_names,
    ReloadClassification,
)
from app.core.utils.pydantic import field_with_metadata
from app.inventory.config import InventorySettings
from app.sep.config import SEPSettings
from app.sep.middleware.messages.config import MessagesSettings
from app.sep.snippets.config import SnippetsSettings
from app.tasks.config import TasksSettings


def test_is_hot_reloadable_true_for_marked_field() -> None:
    """A field marked HOT via ``field_with_metadata`` is detected."""
    assert is_hot_reloadable(SEPSettings, "CONNECTIVITY_CHECK_DEFAULT") is True


def test_is_hot_reloadable_false_for_unmarked_field() -> None:
    """A field on the model but not marked HOT is NOT_OVERRIDABLE.

    ``INVENTORY_ENDPOINT`` is intentionally left unmarked -- guarding
    against accidental promotion here.
    """
    assert is_hot_reloadable(SEPSettings, "INVENTORY_ENDPOINT") is False


def test_is_hot_reloadable_false_for_structural_field() -> None:
    """Structural fields are never overridable."""
    assert is_hot_reloadable(SEPSettings, "PLUGINS") is False


def test_is_hot_reloadable_false_for_missing_field() -> None:
    """An unknown field returns False instead of raising."""
    assert is_hot_reloadable(SEPSettings, "DOES_NOT_EXIST") is False


def test_hot_field_names_sep_settings() -> None:
    """``SEPSettings`` ships exactly the three HOT fields this ticket promotes."""
    assert hot_field_names(SEPSettings) == frozenset(
        {"CONNECTIVITY_CHECK_DEFAULT", "ARTIFACT_DOWNLOAD_TTL", "SYNC_REFRESH_TIME"}
    )


def test_hot_field_names_tasks_settings() -> None:
    """``TasksSettings`` ships the two HOT fields this ticket promotes."""
    assert hot_field_names(TasksSettings) == frozenset(
        {"PRE_EXECUTION_CONNECTIVITY_CHECK", "STALENESS_THRESHOLD_SECONDS"}
    )


def test_nested_overridable_field_names_sep_settings() -> None:
    """``SEPSettings`` ships exactly the two NESTED_ONLY parents this ticket promotes."""
    assert nested_overridable_field_names(SEPSettings) == frozenset(
        {"SESSION", "SESSION_REFRESH"}
    )


def test_nested_overridable_field_names_tasks_settings() -> None:
    """``TasksSettings`` ships the two NESTED_ONLY parents this ticket promotes."""
    assert nested_overridable_field_names(TasksSettings) == frozenset(
        {"NOMAD", "SECURITY_HEADERS"}
    )


def test_hot_field_names_snippets_settings() -> None:
    """``SnippetsSettings`` ships its three HOT preview / sync fields."""
    assert hot_field_names(SnippetsSettings) == frozenset(
        {"ENABLE_MANUAL_SYNC", "PREVIEW_MAX_CHARS", "PREVIEW_MAX_LINES"}
    )


def test_hot_field_names_messages_settings() -> None:
    """``MessagesSettings`` ships ``LEVEL`` as its single HOT field."""
    assert hot_field_names(MessagesSettings) == frozenset({"LEVEL"})


def test_hot_field_names_inventory_settings_empty() -> None:
    """``InventorySettings`` has no HOT fields in this iteration."""
    assert hot_field_names(InventorySettings) == frozenset()


def test_field_without_metadata_returns_false() -> None:
    """A field without any ``CustomFieldMetadata`` returns False without raising."""

    class _Plain(BaseModel):
        value: int = 1

    assert is_hot_reloadable(_Plain, "value") is False


def test_metadata_with_other_keys_does_not_trigger_hot() -> None:
    """Custom metadata other than ``reload`` does not flip the classification."""

    class _Other(BaseModel):
        value: int = field_with_metadata(1, metadata={"unrelated": "yes"})

    assert is_hot_reloadable(_Other, "value") is False


def test_reload_classification_values() -> None:
    """``ReloadClassification`` exposes ``HOT`` and ``NOT_OVERRIDABLE`` values."""
    assert ReloadClassification.HOT.value == "hot"
    assert ReloadClassification.NOT_OVERRIDABLE.value == "not_overridable"
