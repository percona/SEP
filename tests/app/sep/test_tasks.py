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

"""Define tests for app.sep.tasks module."""

from app.sep.tasks import EnhancedPeriodicTaskCreateRequest, PeriodicTaskRequest


def test_periodic_task_request_populates_execute_request_from_prefixed_fields() -> None:
    """Test that PeriodicTaskRequest parses execute_request_ prefixed fields."""
    data = {
        "interval_every": "5",
        "interval_period": "minutes",
        "execute_request_chain_task_names": '["other-task"]',
    }

    request = PeriodicTaskRequest.model_validate(data)

    assert request.execute_request is not None
    assert request.execute_request.chain_task_names == ["other-task"]


def test_periodic_task_request_without_execute_request_prefix_leaves_none() -> None:
    """Test that PeriodicTaskRequest leaves execute_request None when no prefix fields."""
    data = {
        "interval_every": "5",
        "interval_period": "minutes",
    }

    request = PeriodicTaskRequest.model_validate(data)

    assert request.execute_request is None


def test_enhanced_periodic_task_create_request_still_works_with_chain_task_names() -> (
    None
):
    """Test that EnhancedPeriodicTaskCreateRequest populates chain_task_names."""
    data = {
        "task": "my-task",
        "interval_every": "10",
        "interval_period": "hours",
        "execute_request_chain_task_names": '["chain-task"]',
    }

    request = EnhancedPeriodicTaskCreateRequest.model_validate(data)

    assert request.execute_request is not None
    assert request.execute_request.chain_task_names == ["chain-task"]
