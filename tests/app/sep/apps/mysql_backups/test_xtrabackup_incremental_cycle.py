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
"""Tests for the xtrabackup payload's incremental-cycle vocabulary and cadence.

The cycle governs the ``less_space`` incremental method on a run that already has a
usable base backup. Exercising the check directly covers the accepted vocabulary and
the full-versus-incremental decision without staging such a run on disk.
"""

import datetime
import types

import pytest

from app.sep.apps.mysql_backups.forms import BackupCreate
from tests.app.sep.apps.conftest import literal_members
from tests.app.sep.apps.mysql_backups.conftest import XTRABACKUP_INCREMENTAL_CYCLES
from tests.app.sep.apps.mysql_backups.payload_harness import payload_instance

_METHOD = ("_is_ongoing_incremental_cycle",)
_FIELD = "xtrabackup_incremental_cycle"

MONDAY, SATURDAY, SUNDAY = 1, 6, 7
ISO_WEEKDAYS = tuple(range(MONDAY, SUNDAY + 1))

# The reference week starts on a Monday, so ISO weekday N is its Nth day.
_REFERENCE_MONDAY = datetime.date(2026, 1, 5)


def _day(iso_weekday: int) -> datetime.date:
    """Return the reference week's date whose ISO weekday is ``iso_weekday``."""
    return _REFERENCE_MONDAY + datetime.timedelta(days=iso_weekday - 1)


def _backup_dir(day: datetime.date, parent: str = "/backups/svc") -> str:
    """Return a backup directory path named after ``day``, as the payload lays them down."""
    return f"{parent}/{day:%Y-%m-%d}_03-00-00"


def _cycle_checker(
    today: datetime.date = _REFERENCE_MONDAY,
) -> tuple[object, type[Exception], list[str]]:
    """Lift the cycle check onto a frozen clock.

    Both clock reads the method makes -- ``time.strftime()`` for today's date prefix
    and ``datetime.datetime.today()`` for the ISO weekday -- are supplied through the
    exec namespace, so a case picks the weekday it runs on. ``_clean_after_error`` is
    swapped for a recorder (the harness stubs it as a no-op).

    :param today: The date the lifted method sees as today.
    :return: ``(instance, BackupError, cleanups)`` where ``cleanups`` records every
        ``_clean_after_error()`` call.
    """
    instance, backup_error, _ = payload_instance(
        _METHOD,
        extra_namespace={
            "time": types.SimpleNamespace(strftime=today.strftime),
            "datetime": types.SimpleNamespace(
                datetime=types.SimpleNamespace(today=lambda: today)
            ),
        },
    )
    cleanups: list[str] = []
    instance._clean_after_error = lambda: cleanups.append("cleaned")
    return instance, backup_error, cleanups


def test_reference_week_starts_on_a_monday() -> None:
    """Pin the reference week every weekday case derives its dates from."""
    assert _REFERENCE_MONDAY.isoweekday() == MONDAY


class TestAcceptedVocabulary:
    """Cover the cycle values the payload accepts."""

    @pytest.mark.parametrize("cycle", XTRABACKUP_INCREMENTAL_CYCLES)
    def test_accepts_documented_cycle(self, cycle: str) -> None:
        """Reach a cadence decision for ``daily``, ``weekly``, and every ISO weekday."""
        checker, _, _ = _cycle_checker()
        stale_base = _backup_dir(_day(MONDAY) - datetime.timedelta(days=7))
        decision = checker._is_ongoing_incremental_cycle(stale_base, cycle)
        assert isinstance(decision, bool)

    @pytest.mark.parametrize("cycle", literal_members(BackupCreate, _FIELD))
    def test_accepts_every_value_the_create_form_offers(self, cycle: str) -> None:
        """Accept every value the create form can submit.

        Guards the drift this pairing exists to prevent: the form and the payload
        each declare the vocabulary, and a value one side accepts must not be
        rejected by the other.
        """
        checker, _, _ = _cycle_checker()
        decision = checker._is_ongoing_incremental_cycle(
            _backup_dir(_day(MONDAY)), cycle
        )
        assert isinstance(decision, bool)


class TestRejectedVocabulary:
    """Cover the cycle values the payload refuses."""

    @pytest.mark.parametrize(
        "cycle",
        [
            "0",
            "8",
            "-1",
            "01",
            " 1",
            "1 ",
            "",
            "monday",
            "Weekly",
            None,
            1,
            1.0,
        ],
    )
    def test_rejects_value_outside_the_vocabulary(self, cycle: object) -> None:
        """Raise for anything outside the accepted set.

        ``"01"`` and the padded spellings matter: ``int()`` would read them as a
        weekday, so membership has to be tested before the coercion. The ``int`` and
        ``float`` cases pin the vocabulary as string-only, which is what the form
        serialises.
        """
        checker, backup_error, _ = _cycle_checker()
        with pytest.raises(backup_error):
            checker._is_ongoing_incremental_cycle(_backup_dir(_day(MONDAY)), cycle)

    def test_error_names_the_setting_and_the_accepted_set(self) -> None:
        """Name the setting and list every accepted value, Monday included."""
        checker, backup_error, _ = _cycle_checker()
        with pytest.raises(backup_error) as excinfo:
            checker._is_ongoing_incremental_cycle(_backup_dir(_day(MONDAY)), "8")
        message = str(excinfo.value)
        assert "XTRABACKUP_INCREMENTAL_CYCLE" in message
        for cycle in XTRABACKUP_INCREMENTAL_CYCLES:
            assert repr(cycle) in message

    def test_cleans_up_before_raising(self) -> None:
        """Clean up the partial backup exactly once before raising."""
        checker, backup_error, cleanups = _cycle_checker()
        with pytest.raises(backup_error):
            checker._is_ongoing_incremental_cycle(_backup_dir(_day(MONDAY)), "8")
        assert cleanups == ["cleaned"]


class TestWeekdaySelection:
    """Cover the full-versus-incremental decision for a numeric cycle."""

    @pytest.mark.parametrize("iso_weekday", ISO_WEEKDAYS)
    def test_selected_weekday_starts_a_new_cycle(self, iso_weekday: int) -> None:
        """Start a new cycle -- a full backup -- on the selected weekday."""
        today = _day(iso_weekday)
        checker, _, _ = _cycle_checker(today)
        stale_base = _backup_dir(today - datetime.timedelta(days=7))
        assert (
            checker._is_ongoing_incremental_cycle(stale_base, str(iso_weekday)) is False
        )

    @pytest.mark.parametrize("iso_weekday", ISO_WEEKDAYS)
    def test_other_weekdays_keep_the_cycle_ongoing(self, iso_weekday: int) -> None:
        """Keep the cycle ongoing -- incrementals -- on every other weekday."""
        today = _day(iso_weekday)
        checker, _, _ = _cycle_checker(today)
        stale_base = _backup_dir(today - datetime.timedelta(days=7))
        for other in ISO_WEEKDAYS:
            if other == iso_weekday:
                continue
            assert checker._is_ongoing_incremental_cycle(stale_base, str(other)) is True

    def test_sunday_is_seven(self) -> None:
        """Read 7 as Sunday, not as Saturday.

        Pinned separately because ``date.weekday()`` in place of ``isoweekday()``
        would shift the whole mapping by one, and only the last day of the week makes
        the shift visible as a wrong day rather than as an out-of-range value.
        """
        sunday = _day(SUNDAY)
        checker, _, _ = _cycle_checker(sunday)
        stale_base = _backup_dir(sunday - datetime.timedelta(days=7))
        assert checker._is_ongoing_incremental_cycle(stale_base, str(SUNDAY)) is False
        assert checker._is_ongoing_incremental_cycle(stale_base, str(SATURDAY)) is True

    def test_weekly_starts_a_new_cycle_on_monday(self) -> None:
        """Run the ``weekly`` full backup on Monday, exactly as ``1`` does."""
        monday = _day(MONDAY)
        checker, _, _ = _cycle_checker(monday)
        stale_base = _backup_dir(monday - datetime.timedelta(days=7))
        assert checker._is_ongoing_incremental_cycle(stale_base, "weekly") is False
        assert checker._is_ongoing_incremental_cycle(stale_base, str(MONDAY)) is False

    def test_weekly_keeps_the_cycle_ongoing_off_monday(self) -> None:
        """Keep ``weekly`` incremental every other day, exactly as ``1`` does."""
        tuesday = _day(MONDAY + 1)
        checker, _, _ = _cycle_checker(tuesday)
        stale_base = _backup_dir(tuesday - datetime.timedelta(days=7))
        assert checker._is_ongoing_incremental_cycle(stale_base, "weekly") is True
        assert checker._is_ongoing_incremental_cycle(stale_base, str(MONDAY)) is True

    def test_base_from_today_keeps_the_cycle_ongoing(self) -> None:
        """Run one full backup on the selected weekday, not one per run."""
        today = _day(3)
        checker, _, _ = _cycle_checker(today)
        assert checker._is_ongoing_incremental_cycle(_backup_dir(today), "3") is True

    def test_reads_the_leaf_directory_not_the_whole_path(self) -> None:
        """Date-match the leaf directory, ignoring dates in its parents."""
        today = _day(3)
        checker, _, _ = _cycle_checker(today)
        nested = _backup_dir(
            today - datetime.timedelta(days=7), parent=f"/backups/{today:%Y-%m-%d}"
        )
        assert checker._is_ongoing_incremental_cycle(nested, "3") is False


class TestDailyCycle:
    """Cover the ``daily`` cycle, which ignores the weekday entirely."""

    def test_base_from_today_keeps_the_cycle_ongoing(self) -> None:
        """Keep the cycle ongoing once today's full backup is on disk."""
        today = _day(4)
        checker, _, _ = _cycle_checker(today)
        assert (
            checker._is_ongoing_incremental_cycle(_backup_dir(today), "daily") is True
        )

    def test_base_from_yesterday_starts_a_new_cycle(self) -> None:
        """Start a new cycle every day, whatever the weekday."""
        today = _day(4)
        checker, _, _ = _cycle_checker(today)
        yesterday = _backup_dir(today - datetime.timedelta(days=1))
        assert checker._is_ongoing_incremental_cycle(yesterday, "daily") is False
