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

"""Define tests for the app.tasks.alerts module."""

import yaml

from app.tasks.alerts import (
    ARCHIVER_FIELD_PLACEHOLDER,
    ARCHIVER_TRACE_PLACEHOLDER,
    build_archiver_description,
    extract_last_error_trace,
    MAX_TRACE_BYTES,
    parse_archiver_purge_config,
)


def _config_yaml(**overrides) -> str:
    """Build an archiver config YAML string with one PURGE_LIST entry."""
    purge_item = {
        "ALIAS": "TC1",
        "SOURCE_DB": "sbtest",
        "SOURCE_TABLE": "sbtest2",
        "WHERE": "k <= 2000",
        "DEST_DB": "sbtest_archived",
        "DEST_TABLE": "sbtest2",
        "SWAP_DROP": 0,
    }
    purge_item.update(overrides)
    return yaml.dump(
        {
            "ALL": {"SOURCE_HOST": "10.30.50.86", "SOURCE_PORT": 3306},
            "PURGE_LIST": [purge_item],
            "ALIAS": "TC1",
        }
    )


class TestParseArchiverPurgeConfig:
    """Test ``parse_archiver_purge_config``."""

    def test_happy_path(self):
        """Parse the standard config into composed source/condition/target."""
        fields = parse_archiver_purge_config(_config_yaml())
        assert fields is not None
        assert fields.source == "sbtest.sbtest2"
        assert fields.condition == "k <= 2000"
        assert fields.target == "sbtest_archived.sbtest2"

    def test_target_dest_db_falls_back_to_source_db(self):
        """Target uses SOURCE_DB when DEST_DB is absent."""
        fields = parse_archiver_purge_config(_config_yaml(DEST_DB=None))
        assert fields.target == "sbtest.sbtest2"

    def test_target_dest_file_when_no_dest_table(self):
        """Target is the destination file path when no destination table is set."""
        fields = parse_archiver_purge_config(
            _config_yaml(DEST_TABLE=None, DEST_DB=None, DEST_FILE="/backups/out.csv")
        )
        assert fields.target == "/backups/out.csv"

    def test_only_first_purge_list_entry_used(self):
        """Only the first PURGE_LIST entry contributes fields."""
        cfg = yaml.dump(
            {
                "PURGE_LIST": [
                    {"SOURCE_DB": "db1", "SOURCE_TABLE": "t1", "SWAP_DROP": 0},
                    {"SOURCE_DB": "db2", "SOURCE_TABLE": "t2", "SWAP_DROP": 0},
                ],
            }
        )
        fields = parse_archiver_purge_config(cfg)
        assert fields.source == "db1.t1"

    def test_missing_individual_fields_yield_none(self):
        """Absent source/condition/target fields parse to None (not a crash)."""
        cfg = yaml.dump({"PURGE_LIST": [{"SWAP_DROP": 0}]})
        fields = parse_archiver_purge_config(cfg)
        assert fields is not None
        assert fields.source is None
        assert fields.condition is None
        assert fields.target is None

    def test_none_config_returns_none(self):
        """A ``None`` config string returns None."""
        assert parse_archiver_purge_config(None) is None

    def test_invalid_yaml_returns_none(self):
        """Unparseable YAML returns None instead of raising."""
        assert parse_archiver_purge_config("::: not yaml :::\n- [") is None

    def test_empty_purge_list_returns_none(self):
        """An empty PURGE_LIST returns None."""
        assert parse_archiver_purge_config(yaml.dump({"PURGE_LIST": []})) is None

    def test_missing_purge_list_returns_none(self):
        """A config without PURGE_LIST returns None."""
        assert parse_archiver_purge_config(yaml.dump({"ALL": {}})) is None

    def test_scalar_config_returns_none(self):
        """A scalar (non-mapping) config returns None."""
        assert parse_archiver_purge_config("just a string") is None


class TestExtractLastErrorTrace:
    """Test ``extract_last_error_trace``."""

    def test_extracts_last_error_block(self):
        """Return the contiguous block ending at the last ERROR line."""
        stderr = (
            "2026-06-11 17:09:40,001 INFO: PID<1> starting\n"
            "2026-06-11 17:09:48,405 ERROR: PID<498894> E() - first error\n"
            "\n"
            "2026-06-11 17:09:48,405 ERROR: PID<498894> Command returned error:\n"
            "DBD::mysql failed at /usr/bin/pt-archiver line 1929.\n"
            "2026-06-11 17:09:48,405 ERROR: PID<498894> A() - <TC1> Purge Failed\n"
        )
        trace = extract_last_error_trace(stderr)
        # Last block starts after the blank line, drops the leading INFO/first error.
        assert "Command returned error" in trace
        assert "Purge Failed" in trace
        assert "starting" not in trace
        assert "first error" not in trace

    def test_no_error_marker_returns_placeholder(self):
        """STDERR with no ERROR marker yields the placeholder."""
        assert extract_last_error_trace("just some info\nmore info") == (
            ARCHIVER_TRACE_PLACEHOLDER
        )

    def test_none_returns_placeholder(self):
        """A ``None`` stderr yields the placeholder."""
        assert extract_last_error_trace(None) == ARCHIVER_TRACE_PLACEHOLDER

    def test_empty_returns_placeholder(self):
        """Empty/whitespace stderr yields the placeholder."""
        assert extract_last_error_trace("   \n  ") == ARCHIVER_TRACE_PLACEHOLDER

    def test_caps_at_max_trace_bytes(self):
        """An oversized trace is capped to MAX_TRACE_BYTES, keeping the tail."""
        big = "ERROR: " + ("x" * (MAX_TRACE_BYTES * 2)) + "\nERROR: tail marker"
        trace = extract_last_error_trace(big)
        assert len(trace.encode()) <= MAX_TRACE_BYTES
        assert "tail marker" in trace


class TestBuildArchiverDescription:
    """Test ``build_archiver_description``."""

    def test_renders_both_sections(self):
        """Render the two labeled sections with parsed config fields."""
        fields = parse_archiver_purge_config(_config_yaml())
        desc = build_archiver_description(fields, "boom trace", set())
        assert "=== ERROR DETAILS ===" in desc
        assert "boom trace" in desc
        assert "=== ARCHIVER CONFIGURATION ===" in desc
        assert "Source: sbtest.sbtest2" in desc
        assert "Condition: k <= 2000" in desc
        assert "Target: sbtest_archived.sbtest2" in desc

    def test_all_four_labels_present_when_fields_none(self):
        """All labels render with placeholders when config is unavailable."""
        desc = build_archiver_description(None, "boom trace", set())
        assert "boom trace" in desc
        assert f"Source: {ARCHIVER_FIELD_PLACEHOLDER}" in desc
        assert f"Condition: {ARCHIVER_FIELD_PLACEHOLDER}" in desc
        assert f"Target: {ARCHIVER_FIELD_PLACEHOLDER}" in desc

    def test_missing_field_renders_placeholder(self):
        """A single missing config field renders the placeholder for that line."""
        fields = parse_archiver_purge_config(_config_yaml(WHERE=None))
        desc = build_archiver_description(fields, "boom", set())
        assert f"Condition: {ARCHIVER_FIELD_PLACEHOLDER}" in desc
        assert "Source: sbtest.sbtest2" in desc

    def test_empty_entities_passes_through_unscrubbed(self):
        """An empty entity set leaves the description text unchanged."""
        fields = parse_archiver_purge_config(_config_yaml(WHERE="email = 'a@b.com'"))
        desc = build_archiver_description(fields, "boom", set())
        assert "email = 'a@b.com'" in desc

    def test_anonymizes_assembled_block(self, mocker):
        """The assembled block is passed through anonymize_text once."""
        mock_anon = mocker.patch(
            "app.tasks.alerts.anonymize_text", return_value="SCRUBBED"
        )
        from app.tasks.anonymizer.entities import PIIEntity

        fields = parse_archiver_purge_config(_config_yaml())
        entities = {PIIEntity.EMAIL_ADDRESS}
        desc = build_archiver_description(fields, "trace", entities)
        mock_anon.assert_called_once()
        called_text, called_entities = mock_anon.call_args[0][:2]
        assert "=== ERROR DETAILS ===" in called_text
        assert called_entities == entities
        assert desc == "SCRUBBED"
