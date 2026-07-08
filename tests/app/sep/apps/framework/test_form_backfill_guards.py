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

"""Tests for legacy form backfill task-shape guards."""

from types import SimpleNamespace

from app.sep.apps.framework.form_backfill_guards import require_run_python_meta


def test_require_run_python_meta_returns_meta_for_config_bearing_run_python():
    """Return the ``meta`` dict for a ``run-python`` task carrying ``config``."""
    meta = {"config": "SERVER_LIST: []"}
    task = SimpleNamespace(data={"task": "run-python", "meta": meta})

    assert require_run_python_meta(task) is meta


def test_require_run_python_meta_returns_none_for_non_run_python_task():
    """Skip tasks whose command is not ``run-python``."""
    task = SimpleNamespace(data={"task": "run-command", "meta": {"config": "x"}})

    assert require_run_python_meta(task) is None


def test_require_run_python_meta_returns_none_when_meta_is_not_a_dict():
    """Skip tasks whose ``meta`` is not a mapping."""
    task = SimpleNamespace(data={"task": "run-python", "meta": "not-a-dict"})

    assert require_run_python_meta(task) is None


def test_require_run_python_meta_returns_none_when_config_key_is_absent():
    """Skip ``run-python`` tasks whose ``meta`` lacks a ``config`` key."""
    task = SimpleNamespace(data={"task": "run-python", "meta": {"other": "x"}})

    assert require_run_python_meta(task) is None
