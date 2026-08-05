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

"""Collect the per-app declarations that drive the legacy ``data['_form']`` backfill.

Each app package exports ``FORM_BACKFILL_ENTRIES`` naming the tasks it wants
backfilled; the collector walks the ``SEP.APPS`` activation list and merges those
declarations, so the backfill orchestrator names no app.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING

from app.sep.apps.framework.registry import build_app_registry
from app.sep.config import sep_settings

if TYPE_CHECKING:
    from collections.abc import Iterable

    from app.sep.apps.framework.form_backfill import FormReconstructor
    from app.sep.apps.framework.form_dsl import AppFormModel
    from app.sep.config import App

__all__ = ["DECLARATION_ATTR", "FormBackfillEntry", "collect_form_backfill_entries"]

DECLARATION_ATTR = "FORM_BACKFILL_ENTRIES"


@dataclass(frozen=True, slots=True)
class FormBackfillEntry:
    """Declare that an app's legacy tasks are eligible for ``data['_form']`` backfill.

    :param app_key: The declaring app's registry key.
    :param owner: The task owner whose rows the backfill lists.
    :param create_model: The create/update form model the reconstructed body
        must validate against.
    :param reconstructor: The app's legacy form reconstructor.
    """

    app_key: str
    owner: str
    create_model: type[AppFormModel]
    reconstructor: FormReconstructor


def collect_form_backfill_entries(
    plugins: Iterable[App] | None = None,
) -> list[FormBackfillEntry]:
    """Collect backfill entries declared by activated apps, in activation order.

    Each app module may export ``FORM_BACKFILL_ENTRIES`` as a list of
    :class:`FormBackfillEntry` values. Duplicate ``app_key`` values and keys
    absent from the registry fail fast.

    :param plugins: The ``SEP.APPS`` activation entries to scan. Defaults to
        ``sep_settings.APPS``.
    :return: The merged backfill entries.
    :raises ModuleNotFoundError: If an activated app's package is not installed,
        propagating from either import of it.
    :raises TypeError: If a module's declaration is not a list of
        :class:`FormBackfillEntry` instances.
    :raises ValueError: If an app key is declared more than once or is absent
        from the registry, or if ``build_app_registry`` rejects the activation
        list itself.
    """
    activation = list(plugins if plugins is not None else sep_settings.APPS)
    registry = build_app_registry(activation)
    entries: list[FormBackfillEntry] = []
    seen_keys: set[str] = set()
    for plugin in activation:
        declared = getattr(import_module(plugin.module_name), DECLARATION_ATTR, None)
        if declared is None:
            continue
        if not isinstance(declared, list):
            raise TypeError(
                f"App module {plugin.module_name!r}: {DECLARATION_ATTR} must be"
                f" a list, got {type(declared).__name__}.",
            )
        for entry in declared:
            if not isinstance(entry, FormBackfillEntry):
                raise TypeError(
                    f"App module {plugin.module_name!r}: every"
                    f" {DECLARATION_ATTR} entry must be a FormBackfillEntry,"
                    f" got {type(entry).__name__}.",
                )
            if entry.app_key in seen_keys:
                raise ValueError(
                    f"App key {entry.app_key!r} is declared by more than one"
                    " form-backfill registration.",
                )
            if registry.get(entry.app_key) is None:
                raise ValueError(
                    "Form-backfill entry references unknown app key"
                    f" {entry.app_key!r}.",
                )
            seen_keys.add(entry.app_key)
            entries.append(entry)
    return entries
