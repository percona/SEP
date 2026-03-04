"""Define test cases for periodic task models."""

import json
from datetime import datetime, timedelta, UTC

import pytest
from pydantic import ValidationError
from sqlalchemy_celery_beat.models import Period

from app.core.celery.models import CrontabSchedule, IntervalSchedule
from app.tasks.periodic.models import (
    BasePeriodicTask,
    PeriodicTaskCreate,
    PeriodicTaskExecuteRequest,
    PeriodicTaskResponse,
    PeriodicTaskUpdate,
    PeriodicTaskWrite,
)


class TestPeriodicTaskExecuteRequest:
    """Test the PeriodicTaskExecuteRequest model."""

    def test_eta_forced_to_none(self):
        """Assert eta is always forced to None regardless of input."""
        req = PeriodicTaskExecuteRequest(
            eta=datetime(2025, 1, 1, tzinfo=UTC),
            meta={},
        )
        assert req.eta is None

    def test_eta_none_stays_none(self):
        """Assert eta None input remains None."""
        req = PeriodicTaskExecuteRequest(eta=None, meta={})
        assert req.eta is None

    def test_eta_empty_string_forced_to_none(self):
        """Assert empty string eta is forced to None."""
        req = PeriodicTaskExecuteRequest(eta="", meta={})
        assert req.eta is None


class TestBasePeriodicTask:
    """Test the BasePeriodicTask model."""

    @pytest.fixture
    def base_fields(self):
        """Provide shared base fields for building BasePeriodicTask instances."""
        return {
            "name": "test-task",
            "task": "celery.task",
            "start_time": None,
            "enabled": True,
            "description": "desc",
        }

    def test_period_with_interval(self, base_fields):
        """Assert period returns the string representation of the interval."""
        interval = IntervalSchedule(every=5, period=Period.HOURS)
        task = BasePeriodicTask(**base_fields, interval=interval)
        assert task.period == str(interval)

    def test_period_with_crontab(self, base_fields):
        """Assert period returns the string representation of the crontab."""
        crontab = CrontabSchedule(minute="0", hour="12")
        task = BasePeriodicTask(**base_fields, crontab=crontab)
        assert task.period == str(crontab)

    def test_validate_both_none_raises(self, base_fields):
        """Assert ValueError when both interval and crontab are None."""
        with pytest.raises(ValidationError, match="Either `interval` or `crontab`"):
            BasePeriodicTask(**base_fields)

    def test_validate_both_set_raises(self, base_fields):
        """Assert ValueError when both interval and crontab are set."""
        with pytest.raises(ValidationError, match="Only one of"):
            BasePeriodicTask(
                **base_fields,
                interval=IntervalSchedule(every=1, period=Period.HOURS),
                crontab=CrontabSchedule(),
            )

    def test_validate_exactly_one_passes(self, base_fields):
        """Assert validation passes when exactly one schedule is set."""
        task = BasePeriodicTask(
            **base_fields,
            interval=IntervalSchedule(every=1, period=Period.HOURS),
        )
        assert task.interval is not None
        assert task.crontab is None


class TestPeriodicTaskResponse:
    """Test the PeriodicTaskResponse model."""

    def test_populate_task_data_from_dict_with_kwargs(self):
        """Assert task data is populated from kwargs in a dict."""
        data = {
            "id": 1,
            "name": "test",
            "task": "original-task",
            "start_time": None,
            "enabled": True,
            "description": "",
            "last_run_at": None,
            "total_run_count": 0,
            "date_changed": None,
            "args": "[]",
            "kwargs": json.dumps(
                {"task_name": "my-backup", "execution_data": {"meta": {}}}
            ),
            "model_intervalschedule": IntervalSchedule(every=1, period=Period.HOURS),
        }
        response = PeriodicTaskResponse.model_validate(data)
        assert response.task == "my-backup"
        assert response.execute_request is not None
        assert response.execute_request.meta == {}

    def test_populate_task_data_from_dict_with_args(self):
        """Assert task data is populated from positional args in a dict."""
        data = {
            "id": 1,
            "name": "test",
            "task": "original-task",
            "start_time": None,
            "enabled": True,
            "description": "",
            "last_run_at": None,
            "total_run_count": 0,
            "date_changed": None,
            "args": json.dumps(["my-backup-task", {"meta": {"key": "val"}}]),
            "kwargs": "{}",
            "model_intervalschedule": IntervalSchedule(every=1, period=Period.HOURS),
        }
        response = PeriodicTaskResponse.model_validate(data)
        assert response.task == "my-backup-task"
        assert response.execute_request is not None
        assert response.execute_request.meta == {"key": "val"}

    def test_populate_task_data_kwargs_overrides_args(self):
        """Assert kwargs take precedence over args for task_name."""
        data = {
            "id": 1,
            "name": "test",
            "task": "original-task",
            "start_time": None,
            "enabled": True,
            "description": "",
            "last_run_at": None,
            "total_run_count": 0,
            "date_changed": None,
            "args": json.dumps(["args-task"]),
            "kwargs": json.dumps({"task_name": "kwargs-task"}),
            "model_intervalschedule": IntervalSchedule(every=1, period=Period.HOURS),
        }
        response = PeriodicTaskResponse.model_validate(data)
        assert response.task == "kwargs-task"

    def test_populate_task_data_empty_args_and_kwargs_raises(self):
        """Assert ValidationError when both args and kwargs are empty."""
        data = {
            "id": 1,
            "name": "test",
            "task": "original-task",
            "start_time": None,
            "enabled": True,
            "description": "",
            "last_run_at": None,
            "total_run_count": 0,
            "date_changed": None,
            "args": "[]",
            "kwargs": "{}",
            "model_intervalschedule": IntervalSchedule(every=1, period=Period.HOURS),
        }
        with pytest.raises(ValidationError, match="task"):
            PeriodicTaskResponse.model_validate(data)


class TestPeriodicTaskWrite:
    """Test the PeriodicTaskWrite model."""

    def test_populate_celery_task_data(self):
        """Assert celery task name and kwargs are populated from input."""
        data = {
            "name": "test-write",
            "task": "my-sep-task",
            "start_time": None,
            "enabled": True,
            "description": "",
            "execute_request": {"meta": {}},
            "interval": {"every": 10, "period": "minutes"},
        }
        task = PeriodicTaskWrite.model_validate(data)
        assert task.task == "app.tasks.celery.execute_task_by_name"
        parsed_kwargs = json.loads(task.kwargs)
        assert parsed_kwargs["task_name"] == "my-sep-task"
        assert parsed_kwargs["execution_data"] == {"meta": {}}

    def test_encode_kwargs_dict_to_json(self):
        """Assert dict kwargs are encoded to JSON string."""
        data = {
            "name": "test",
            "task": "my-task",
            "start_time": None,
            "enabled": True,
            "description": "",
            "interval": {"every": 1, "period": "hours"},
        }
        task = PeriodicTaskWrite.model_validate(data)
        assert isinstance(task.kwargs, str)
        parsed = json.loads(task.kwargs)
        assert isinstance(parsed, dict)

    def test_encode_kwargs_string_passthrough(self):
        """Assert string kwargs pass through the field validator unchanged."""
        task = PeriodicTaskWrite.model_validate(
            {
                "name": "test",
                "task": "my-task",
                "start_time": None,
                "enabled": True,
                "description": "",
                "interval": {"every": 1, "period": "hours"},
            }
        )
        assert isinstance(task.kwargs, str)
        parsed = json.loads(task.kwargs)
        assert "task_name" in parsed

    def test_validate_min_interval_valid_periods(self):
        """Assert valid periods (DAYS, HOURS, MINUTES) pass validation."""
        for period in (Period.DAYS, Period.HOURS, Period.MINUTES):
            data = {
                "name": "test",
                "task": "my-task",
                "start_time": None,
                "enabled": True,
                "description": "",
                "interval": {"every": 1, "period": period.value},
            }
            task = PeriodicTaskWrite.model_validate(data)
            assert task.interval.period == period

    def test_validate_min_interval_invalid_period_raises(self):
        """Assert ValueError for SECONDS period."""
        data = {
            "name": "test",
            "task": "my-task",
            "start_time": None,
            "enabled": True,
            "description": "",
            "interval": {"every": 1, "period": "seconds"},
        }
        with pytest.raises(ValidationError, match="Invalid period"):
            PeriodicTaskWrite.model_validate(data)

    def test_validate_min_interval_microseconds_raises(self):
        """Assert ValueError for MICROSECONDS period."""
        data = {
            "name": "test",
            "task": "my-task",
            "start_time": None,
            "enabled": True,
            "description": "",
            "interval": {"every": 1, "period": "microseconds"},
        }
        with pytest.raises(ValidationError, match="Invalid period"):
            PeriodicTaskWrite.model_validate(data)


class TestPeriodicTaskUpdate:
    """Test the PeriodicTaskUpdate model."""

    def test_encode_kwargs_missing_task_name_raises(self):
        """Assert ValueError when task_name is None in kwargs."""
        with pytest.raises(ValidationError, match="task_name"):
            PeriodicTaskUpdate.model_validate(
                {
                    "name": "test",
                    "task": None,
                    "start_time": None,
                    "enabled": True,
                    "description": "",
                    "interval": {"every": 1, "period": "hours"},
                }
            )

    def test_encode_kwargs_with_task_name_passes(self):
        """Assert kwargs with task_name passes validation."""
        task = PeriodicTaskUpdate.model_validate(
            {
                "name": "test",
                "task": "my-task",
                "start_time": None,
                "enabled": True,
                "description": "",
                "interval": {"every": 1, "period": "hours"},
                "kwargs": {"task_name": "my-task", "execution_data": None},
            }
        )
        parsed = json.loads(task.kwargs)
        assert parsed["task_name"] == "my-task"


class TestPeriodicTaskCreate:
    """Test the PeriodicTaskCreate model."""

    def test_defaults(self):
        """Assert default values for PeriodicTaskCreate."""
        task = PeriodicTaskCreate.model_validate(
            {
                "task": "my-task",
                "interval": {"every": 1, "period": "hours"},
            }
        )
        assert task.name == ""
        assert task.start_time is None
        assert task.enabled is True
        assert task.description == ""


class TestPeriodicTaskResponseNextRunAt:
    """Test the next_run_at computed field on PeriodicTaskResponse."""

    @pytest.fixture
    def response_fields(self):
        """Provide shared fields for building PeriodicTaskResponse instances."""
        return {
            "id": 1,
            "name": "test",
            "task": "original-task",
            "start_time": None,
            "enabled": True,
            "description": "",
            "last_run_at": None,
            "total_run_count": 0,
            "date_changed": None,
            "args": json.dumps(["my-task"]),
            "kwargs": "{}",
        }

    def test_crontab_next_run_is_future_utc(self, response_fields):
        """Assert next_run_at returns a future UTC datetime for crontab tasks."""
        response_fields["model_crontabschedule"] = CrontabSchedule(
            minute="0", hour="*/1"
        )
        response = PeriodicTaskResponse.model_validate(response_fields)
        assert response.next_run_at is not None
        assert response.next_run_at > datetime.now(UTC)
        assert response.next_run_at.tzinfo is not None

    def test_crontab_non_utc_timezone_returns_utc(self, response_fields):
        """Assert next_run_at converts non-UTC crontab timezone to UTC."""
        response_fields["model_crontabschedule"] = CrontabSchedule(
            minute="0", hour="*/1", timezone="America/New_York"
        )
        response = PeriodicTaskResponse.model_validate(response_fields)
        assert response.next_run_at is not None
        assert response.next_run_at.tzinfo == UTC

    def test_interval_next_run_with_last_run_at(self, response_fields):
        """Assert next_run_at equals last_run_at plus the interval."""
        last_run = datetime(2026, 3, 3, 10, 0, 0, tzinfo=UTC)
        response_fields["last_run_at"] = last_run
        response_fields["model_intervalschedule"] = IntervalSchedule(
            every=5, period=Period.HOURS
        )
        response = PeriodicTaskResponse.model_validate(response_fields)
        assert response.next_run_at == last_run + timedelta(hours=5)

    def test_interval_next_run_falls_back_to_start_time(self, response_fields):
        """Assert next_run_at uses start_time when last_run_at is None."""
        start = datetime(2026, 3, 3, 8, 0, 0, tzinfo=UTC)
        response_fields["start_time"] = start
        response_fields["model_intervalschedule"] = IntervalSchedule(
            every=30, period=Period.MINUTES
        )
        response = PeriodicTaskResponse.model_validate(response_fields)
        assert response.next_run_at == start + timedelta(minutes=30)

    def test_interval_next_run_falls_back_to_now(self, response_fields):
        """Assert next_run_at is close to now + interval when no base time exists."""
        response_fields["model_intervalschedule"] = IntervalSchedule(
            every=2, period=Period.DAYS
        )
        before = datetime.now(UTC)
        response = PeriodicTaskResponse.model_validate(response_fields)
        expected = before + timedelta(days=2)
        assert abs((response.next_run_at - expected).total_seconds()) < 1

    def test_disabled_task_returns_none(self, response_fields):
        """Assert next_run_at is None for disabled tasks."""
        response_fields["enabled"] = False
        response_fields["model_intervalschedule"] = IntervalSchedule(
            every=1, period=Period.HOURS
        )
        response = PeriodicTaskResponse.model_validate(response_fields)
        assert response.next_run_at is None
