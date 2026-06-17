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

from types import SimpleNamespace

import pytest
import yaml

from app.tasks.alerts import (
    _effective_entities,
    ARCHIVER_FIELD_PLACEHOLDER,
    ARCHIVER_TRACE_PLACEHOLDER,
    build_archiver_description,
    build_owner_alert_details,
    extract_last_error_trace,
    MAX_TRACE_BYTES,
    parse_archiver_purge_config,
    redact_secrets,
)
from app.tasks.anonymizer.entities import PIIEntity


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

    def test_redacts_credentials_with_empty_entities(self):
        """Credentials are stripped even when no PII mask is configured.

        Regression for SEP-1340: redaction is mask-independent, so a DSN/password
        echoed in the trace never reaches the provider despite the default-off
        PII mask (empty entity set).
        """
        trace = "DBI connect('h=db1,P=3306,u=root,p=s3cr3t') failed"
        desc = build_archiver_description(None, trace, set())
        assert "s3cr3t" not in desc
        assert "p=***" in desc
        # The non-secret DSN parts (and the port) survive.
        assert "h=db1" in desc
        assert "P=3306" in desc


class TestRedactSecrets:
    """Test ``redact_secrets``."""

    def test_masks_uri_userinfo(self):
        """A ``scheme://user:pass@host`` URI has its userinfo masked."""
        assert redact_secrets("mysql://admin:hunter2@db:3306/x") == (
            "mysql://***@db:3306/x"
        )

    def test_masks_password_key_value(self):
        """``password=``/``passwd=``/``pwd=`` values are masked (case-insensitive)."""
        assert "hunter2" not in redact_secrets("password=hunter2")
        assert "hunter2" not in redact_secrets("PASSWD: hunter2")
        assert "hunter2" not in redact_secrets("pwd=hunter2&x=1")

    def test_masks_dsn_lowercase_p_only(self):
        """The DBI DSN ``p=`` (password) is masked; ``P=`` (port) is preserved."""
        out = redact_secrets("h=db1,P=3306,u=root,p=s3cr3t")
        assert "s3cr3t" not in out
        assert "p=***" in out
        assert "P=3306" in out

    def test_masks_cli_password_flags(self):
        """``--password=``, ``--password `` and ``-p`` CLI flags are masked."""
        assert "topsecret" not in redact_secrets("pt-archiver --password=topsecret")
        assert "topsecret" not in redact_secrets("pt-archiver --password topsecret")
        assert "topsecret" not in redact_secrets("mysql -ptopsecret")

    def test_leaves_clean_text_unchanged(self):
        """Text with no credentials is returned verbatim."""
        clean = "ERROR: Purge Failed on sbtest.sbtest2 where k <= 2000"
        assert redact_secrets(clean) == clean


class TestEffectiveEntities:
    """Test ``_effective_entities`` mask precedence."""

    @staticmethod
    def _history(history_mask, task_mask):
        """Return a stub history exposing the two anonymize masks."""
        return SimpleNamespace(
            anonymize_mask=history_mask,
            task=SimpleNamespace(anonymize_mask=task_mask),
        )

    def test_history_mask_wins(self):
        """The history-level mask is used when present."""
        history = self._history(int(PIIEntity.EMAIL_ADDRESS), int(PIIEntity.IP_ADDRESS))
        assert _effective_entities(history) == {PIIEntity.EMAIL_ADDRESS}

    def test_falls_back_to_task_mask(self):
        """The owning task's mask is used when the history has none."""
        history = self._history(None, int(PIIEntity.IP_ADDRESS))
        assert _effective_entities(history) == {PIIEntity.IP_ADDRESS}

    def test_both_none_yields_empty_set(self):
        """No mask anywhere yields an empty set (no PII scrubbing)."""
        assert _effective_entities(self._history(None, None)) == set()


class TestBuildOwnerAlertDetails:
    """Test ``build_owner_alert_details`` orchestration edge cases."""

    @staticmethod
    def _archiver_history(*, exec_meta, task_data, target="executor-host"):
        """Return a stub ARCHIVER history for the detail builder."""
        from app.tasks.models import TaskOwner

        return SimpleNamespace(
            id=42,
            task=SimpleNamespace(
                owner=TaskOwner.ARCHIVER, data=task_data, anonymize_mask=None
            ),
            execution_request=SimpleNamespace(meta=exec_meta, target=target),
            anonymize_mask=None,
        )

    @pytest.mark.asyncio
    async def test_returns_none_for_non_archiver(self, mocker):
        """A non-archiver task yields ``None`` (generic path unchanged)."""
        from app.tasks.models import TaskOwner

        history = SimpleNamespace(
            task=SimpleNamespace(owner=TaskOwner.ANY, data={}, anonymize_mask=None),
            execution_request=SimpleNamespace(meta={}, target="t"),
            anonymize_mask=None,
            id=1,
        )
        assert await build_owner_alert_details(history) is None

    @pytest.mark.asyncio
    async def test_falls_back_to_task_data_meta_when_snapshot_empty(self, mocker):
        """When the execution snapshot meta is empty, fall back to task.data meta.

        Covers legacy histories whose ``execution_request.meta`` is empty: the
        builder reads ``task.data["meta"]`` so source node + config still render.
        """
        mocker.patch(
            "app.tasks.alerts._read_last_stderr",
            return_value="ERROR: boom",
        )
        meta = {
            "config": _config_yaml(SOURCE_DB="legacy_db", SOURCE_TABLE="legacy_tbl"),
            "_pmm_node_name": "legacy-node",
        }
        history = self._archiver_history(exec_meta={}, task_data={"meta": meta})

        details = await build_owner_alert_details(history)
        assert details is not None
        assert details.source_node == "legacy-node"
        assert "Source: legacy_db.legacy_tbl" in details.custom_details["description"]

    @pytest.mark.asyncio
    async def test_stderr_read_failure_yields_placeholder_not_crash(self, mocker):
        """A STDERR-read failure must not abort the alert; use the placeholder.

        ``_read_last_stderr`` swallows any read error and returns ``None`` so the
        failure alert still fires with the trace placeholder.
        """
        mocker.patch(
            "app.tasks.db.get_async_session_maker",
            side_effect=RuntimeError("db down"),
        )
        meta = {"config": _config_yaml(), "_pmm_node_name": "node-x"}
        history = self._archiver_history(exec_meta=meta, task_data={})

        details = await build_owner_alert_details(history)
        assert details is not None
        assert ARCHIVER_TRACE_PLACEHOLDER in details.custom_details["description"]
