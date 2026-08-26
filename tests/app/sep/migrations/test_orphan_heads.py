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

"""Define tests for the SEP orphan-head filtering helpers.

Exercise ``partition_heads`` and ``empty_version_locations`` against the
real ``alembic.ini`` revision map — the two pure halves of the fail-closed
decision ``skip_unresolvable_heads`` makes, whose combination is covered by
the integration tests in ``test_alembic_integration.py``.
"""

import logging
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.sep.migrations._orphan_heads import (
    empty_version_locations,
    partition_heads,
    skip_unresolvable_heads,
)

from .conftest import ALEMBIC_INI, ALERTS_HEAD, UNKNOWN_REVISION, write_revision

_ORPHAN_HEADS_LOGGER = "app.sep.migrations._orphan_heads"

# The create_atw_incident_tables revision, on the atw branch.
_ATW_REVISION = "b82887dfe93d"
# The create_mysql_backup_run_table revision, on the mysql_backups branch.
_MYSQL_BACKUPS_HEAD = "f0a1b2c3d4e5"


@pytest.fixture
def sep_script() -> ScriptDirectory:
    """Return the script directory built from the real sep Alembic config.

    :return: The ``ScriptDirectory`` for the sep track's revision map.
    """
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI), ini_section="sep"))


def test_partition_heads_splits_known_from_unknown(sep_script):
    """Sort a resolvable revision and an unknown one into separate tuples."""
    resolvable, unresolvable = partition_heads(
        sep_script, (ALERTS_HEAD, UNKNOWN_REVISION)
    )

    assert resolvable == (ALERTS_HEAD,)
    assert unresolvable == (UNKNOWN_REVISION,)


def test_partition_heads_treats_every_real_head_as_resolvable(sep_script):
    """Leave ``unresolvable`` empty for the heads the tree actually defines."""
    heads = tuple(rev.revision for rev in sep_script.get_revisions("heads"))

    resolvable, unresolvable = partition_heads(sep_script, heads)

    assert set(resolvable) == set(heads)
    assert unresolvable == ()


def test_partition_heads_on_empty_input_makes_no_revision_map_lookups():
    """Return two empty tuples without dereferencing the revision map.

    The stub's ``revision_map`` is ``None``, so any lookup would raise
    ``AttributeError`` rather than return a wrong answer.
    """
    stub_script = SimpleNamespace(revision_map=None)

    assert partition_heads(stub_script, ()) == ((), ())


def test_partition_heads_preserves_input_order(sep_script):
    """Keep resolvable ids in the order they appeared in ``heads``."""
    resolvable, unresolvable = partition_heads(
        sep_script, (_ATW_REVISION, UNKNOWN_REVISION, _MYSQL_BACKUPS_HEAD)
    )

    assert resolvable == (_ATW_REVISION, _MYSQL_BACKUPS_HEAD)
    assert unresolvable == (UNKNOWN_REVISION,)


def test_partition_heads_reports_several_unknown_ids(sep_script):
    """Collect every unresolvable id, as an app with unmerged heads produces."""
    _, unresolvable = partition_heads(
        sep_script, (UNKNOWN_REVISION, "cafebabe5678", ALERTS_HEAD)
    )

    assert unresolvable == (UNKNOWN_REVISION, "cafebabe5678")


def test_empty_version_locations_is_empty_when_every_entry_is_populated(sep_script):
    """Report nothing empty for the checked-in configuration."""
    assert empty_version_locations(sep_script) == (), (
        "A configured [sep] version_locations entry contributes no revisions, so "
        "skip_unresolvable_heads will read this tree as a stripped app and stop "
        "treating an unresolvable revision as version skew. Add the app's first "
        "revision, or drop the entry — don't relax this assertion."
    )


def test_empty_version_locations_reports_an_absent_entry(tmp_path):
    """Name the configured location that is not a directory on disk."""
    absent = tmp_path / "gone"
    cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    script = ScriptDirectory.from_config(cfg)
    cfg.set_main_option(
        "version_locations", ":".join([*script.version_locations, str(absent)])
    )

    assert empty_version_locations(ScriptDirectory.from_config(cfg)) == (str(absent),)


def test_empty_version_locations_reports_a_present_but_empty_entry(tmp_path):
    """Name a configured directory that exists but contributes no revisions."""
    empty = tmp_path / "scaffold" / "versions"
    empty.mkdir(parents=True)
    cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    script = ScriptDirectory.from_config(cfg)
    cfg.set_main_option(
        "version_locations", ":".join([*script.version_locations, str(empty)])
    )

    assert empty_version_locations(ScriptDirectory.from_config(cfg)) == (str(empty),)


def test_empty_version_locations_matches_populated_dir_via_symlink(tmp_path):
    """Do not treat a populated location as empty when configured via a symlink.

    Alembic stores resolved ``rev.path`` parents; comparing unresolved
    configured paths against those parents falsely armed the filter on trees
    where the spelling differs (for example a ``/tmp`` symlink).
    """
    revision = "symlink000001"
    real = tmp_path / "real" / "versions"
    write_revision(real, revision, "symlink")
    link_parent = tmp_path / "via_link"
    link_parent.mkdir()
    linked = link_parent / "versions"
    linked.symlink_to(real)
    assert str(linked) != str(linked.resolve())

    cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    cfg.set_main_option("version_locations", str(linked))
    script = ScriptDirectory.from_config(cfg)

    assert empty_version_locations(script) == ()
    assert script.get_revision(revision) is not None


def test_empty_version_locations_tolerates_unset_locations():
    """Return an empty tuple when the ini omits ``version_locations``."""
    stub_script = SimpleNamespace(version_locations=None, walk_revisions=lambda: [])

    assert empty_version_locations(stub_script) == ()


class TestFailClosedDiagnostic:
    """Cover the ERROR logged when every configured location is populated."""

    @staticmethod
    def _read_fail_closed_error(sep_script, caplog) -> str:
        """Run the filter over an unresolvable head and return the ERROR text.

        :param sep_script: Script directory whose locations are all populated.
        :param caplog: Pytest log-capture fixture.
        :return: The single ERROR message the filter emitted.
        """
        migration_context = SimpleNamespace(
            get_current_heads=lambda: (UNKNOWN_REVISION,),
            version_table="alembic_version_sep",
        )
        env_context = SimpleNamespace(
            get_context=lambda: migration_context, script=sep_script
        )
        skip_unresolvable_heads(env_context)

        with caplog.at_level(logging.ERROR, logger=_ORPHAN_HEADS_LOGGER):
            assert migration_context.get_current_heads() == (UNKNOWN_REVISION,)

        records = [
            record
            for record in caplog.records
            if record.name == _ORPHAN_HEADS_LOGGER and record.levelno == logging.ERROR
        ]
        assert len(records) == 1
        return records[0].getMessage()

    @pytest.mark.parametrize(
        "cause", ["version skew", "squashed revision", "version_locations"]
    )
    def test_offers_each_candidate_cause(self, sep_script, caplog, cause):
        """Name every explanation an operator has to rule out by hand."""
        assert cause in self._read_fail_closed_error(sep_script, caplog)

    def test_does_not_rule_out_a_stripped_app(self, sep_script, caplog):
        """Leave a stripped app in play: a pruned entry hides the evidence."""
        message = self._read_fail_closed_error(sep_script, caplog)

        assert message
        assert "not a stripped app" not in message

    def test_names_what_the_operator_has_to_look_at(self, sep_script, caplog):
        """Point at the offending revision and the table recording it."""
        message = self._read_fail_closed_error(sep_script, caplog)

        assert UNKNOWN_REVISION in message
        assert "alembic_version_sep" in message

    def test_requires_every_location_to_contribute_a_revision(self, sep_script, caplog):
        """State the widened fail-closed condition in the ERROR text."""
        message = self._read_fail_closed_error(sep_script, caplog)

        assert "contributes at least one revision" in message
