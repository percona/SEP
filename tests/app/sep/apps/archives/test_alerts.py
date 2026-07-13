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

"""Define tests for the app.sep.apps.archives.alerts module."""

from types import SimpleNamespace

import pytest
import yaml

from app.sep.apps.archives.alerts import (
    _effective_entities,
    _reconstruct_error_tail,
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
        """Use SOURCE_DB for the target when DEST_DB is absent."""
        fields = parse_archiver_purge_config(_config_yaml(DEST_DB=None))
        assert fields.target == "sbtest.sbtest2"

    def test_target_dest_file_when_no_dest_table(self):
        """Use the destination file path as target when no destination table is set."""
        fields = parse_archiver_purge_config(
            _config_yaml(DEST_TABLE=None, DEST_DB=None, DEST_FILE="/backups/out.csv")
        )
        assert fields.target == "/backups/out.csv"

    def test_only_first_purge_list_entry_used(self):
        """Use only the first PURGE_LIST entry's fields."""
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
        """Parse absent source/condition/target fields to None (not a crash)."""
        cfg = yaml.dump({"PURGE_LIST": [{"SWAP_DROP": 0}]})
        fields = parse_archiver_purge_config(cfg)
        assert fields is not None
        assert fields.source is None
        assert fields.condition is None
        assert fields.target is None

    def test_none_config_returns_none(self):
        """Return None for a ``None`` config string."""
        assert parse_archiver_purge_config(None) is None

    def test_invalid_yaml_returns_none(self):
        """Return None for unparseable YAML instead of raising."""
        assert parse_archiver_purge_config("::: not yaml :::\n- [") is None

    def test_empty_purge_list_returns_none(self):
        """Return None for an empty PURGE_LIST."""
        assert parse_archiver_purge_config(yaml.dump({"PURGE_LIST": []})) is None

    def test_missing_purge_list_returns_none(self):
        """Return None for a config without PURGE_LIST."""
        assert parse_archiver_purge_config(yaml.dump({"ALL": {}})) is None

    def test_scalar_config_returns_none(self):
        """Return None for a scalar (non-mapping) config."""
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
        """Return the placeholder for STDERR with no ERROR marker."""
        assert extract_last_error_trace("just some info\nmore info") == (
            ARCHIVER_TRACE_PLACEHOLDER
        )

    def test_none_returns_placeholder(self):
        """Return the placeholder for a ``None`` stderr."""
        assert extract_last_error_trace(None) == ARCHIVER_TRACE_PLACEHOLDER

    def test_empty_returns_placeholder(self):
        """Return the placeholder for empty/whitespace stderr."""
        assert extract_last_error_trace("   \n  ") == ARCHIVER_TRACE_PLACEHOLDER

    def test_caps_at_max_trace_bytes(self):
        """Cap an oversized trace to MAX_TRACE_BYTES, keeping the tail."""
        big = "ERROR: " + ("x" * (MAX_TRACE_BYTES * 2)) + "\nERROR: tail marker"
        trace = extract_last_error_trace(big)
        assert len(trace.encode()) <= MAX_TRACE_BYTES
        assert "tail marker" in trace


class TestReconstructErrorTail:
    """Test ``_reconstruct_error_tail`` chunk reassembly."""

    def test_returns_joined_stderr_tail(self):
        """Join a short multi-chunk stream whole, in chronological order.

        Chunks arrive newest-first; the reconstructed tail restores stream
        order so the downstream extractor sees the complete tail rather than
        just the final chunk.
        """
        # newest-first: ["last error", "first error"]
        assert _reconstruct_error_tail(["last error", "first error"]) == (
            "first errorlast error"
        )

    def test_returns_tail_when_error_marker_in_earlier_chunk(self):
        """Scan back past the newest chunk so a straddling ERROR block survives.

        The last error block can straddle a chunk boundary, with the ``ERROR``
        marker in an earlier chunk and only the trailing continuation lines in
        the newest chunk. Reading just the newest chunk would drop the marker.
        """
        chunks = [
            "DBD::mysql failed at line 1929.\n",
            "prelude\nERROR: pt-archiver Purge Failed\n",
        ]
        content = _reconstruct_error_tail(chunks)
        assert content is not None
        assert "ERROR: pt-archiver Purge Failed" in content
        assert "DBD::mysql failed at line 1929." in content

    def test_detects_marker_split_across_chunk_boundary(self):
        """Detect an ERROR marker split across the chunk boundary.

        The ``ERROR`` token itself can land half in one chunk and half in the
        next (``"...ER" | "ROR: ..."``). The reverse scan bridges adjacent
        chunks with a short prefix so the split marker is still recognized.
        """
        # newest-first: ["ROR: boom\n", "prelude ER"]
        assert _reconstruct_error_tail(["ROR: boom\n", "prelude ER"]) == (
            "prelude ERROR: boom\n"
        )

    def test_stops_scanning_once_marker_and_min_bytes_reached(self):
        """Stop the reverse scan after the marker plus the trailing byte budget.

        When the newest chunk already holds the marker and exceeds the trailing
        byte budget, older chunks are not pulled into the result.
        """
        big = "ERROR: " + ("x" * (4 * 1024))
        # newest-first: [big, "OLD CONTEXT\n"]
        content = _reconstruct_error_tail([big, "OLD CONTEXT\n"])
        assert content is not None
        assert content.startswith("ERROR: ")
        assert "OLD CONTEXT" not in content

    def test_returns_none_for_no_chunks(self):
        """Return None when there are no STDERR chunks."""
        assert _reconstruct_error_tail([]) is None


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
        """Render all labels with placeholders when config is unavailable."""
        desc = build_archiver_description(None, "boom trace", set())
        assert "boom trace" in desc
        assert f"Source: {ARCHIVER_FIELD_PLACEHOLDER}" in desc
        assert f"Condition: {ARCHIVER_FIELD_PLACEHOLDER}" in desc
        assert f"Target: {ARCHIVER_FIELD_PLACEHOLDER}" in desc

    def test_missing_field_renders_placeholder(self):
        """Render the placeholder for a single missing config field's line."""
        fields = parse_archiver_purge_config(_config_yaml(WHERE=None))
        desc = build_archiver_description(fields, "boom", set())
        assert f"Condition: {ARCHIVER_FIELD_PLACEHOLDER}" in desc
        assert "Source: sbtest.sbtest2" in desc

    def test_empty_entities_passes_through_unscrubbed(self):
        """Leave the description text unchanged for an empty entity set."""
        fields = parse_archiver_purge_config(_config_yaml(WHERE="email = 'a@b.com'"))
        desc = build_archiver_description(fields, "boom", set())
        assert "email = 'a@b.com'" in desc

    def test_anonymizes_assembled_block(self, mocker):
        """Pass the assembled block through anonymize_text once."""
        mock_anon = mocker.patch(
            "app.sep.apps.archives.alerts.anonymize_text", return_value="SCRUBBED"
        )
        fields = parse_archiver_purge_config(_config_yaml())
        entities = {PIIEntity.EMAIL_ADDRESS}
        desc = build_archiver_description(fields, "trace", entities)
        mock_anon.assert_called_once()
        called_text, called_entities = mock_anon.call_args[0][:2]
        assert "=== ERROR DETAILS ===" in called_text
        assert called_entities == entities
        assert desc == "SCRUBBED"

    def test_redacts_credentials_with_empty_entities(self):
        """Strip credentials even when no PII mask is configured.

        Redaction is mask-independent, so a DSN/password echoed in the trace
        never reaches the provider despite the default-off PII mask (empty
        entity set).
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
        """Mask the userinfo of a ``scheme://user:pass@host`` URI."""
        assert redact_secrets("mysql://admin:hunter2@db:3306/x") == (
            "mysql://***@db:3306/x"
        )

    def test_masks_password_key_value(self):
        """Mask ``password=``/``passwd=``/``pwd=`` values (case-insensitive)."""
        assert "hunter2" not in redact_secrets("password=hunter2")
        assert "hunter2" not in redact_secrets("PASSWD: hunter2")
        assert "hunter2" not in redact_secrets("pwd=hunter2&x=1")

    def test_masks_dsn_lowercase_p_only(self):
        """Mask the DBI DSN ``p=`` (password) but preserve ``P=`` (port)."""
        out = redact_secrets("h=db1,P=3306,u=root,p=s3cr3t")
        assert "s3cr3t" not in out
        assert "p=***" in out
        assert "P=3306" in out

    def test_masks_cli_password_flags(self):
        """Mask ``--password=``, ``--password `` and ``-p`` CLI flags."""
        assert "topsecret" not in redact_secrets("pt-archiver --password=topsecret")
        assert "topsecret" not in redact_secrets("pt-archiver --password topsecret")
        assert "topsecret" not in redact_secrets("mysql -ptopsecret")

    def test_dash_p_inside_long_flags_not_masked(self):
        """Leave non-secret ``-p`` substrings (e.g. ``--purge``) untouched.

        The ``-p`` short flag is anchored to an argument boundary, so the ``-p``
        inside ``--purge``/``--progress``/``--output-path`` — and the ``-P``
        (port) flag — survive intact; only a real ``-pSECRET`` token is masked.
        """
        cmd = "pt-archiver --purge --progress 1000 --output-path=/tmp/out -P 3306"
        assert redact_secrets(cmd) == cmd

    def test_leaves_clean_text_unchanged(self):
        """Return text with no credentials verbatim."""
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
        """Use the history-level mask when present."""
        history = self._history(int(PIIEntity.EMAIL_ADDRESS), int(PIIEntity.IP_ADDRESS))
        assert _effective_entities(history) == {PIIEntity.EMAIL_ADDRESS}

    def test_falls_back_to_task_mask(self):
        """Use the owning task's mask when the history has none."""
        history = self._history(None, int(PIIEntity.IP_ADDRESS))
        assert _effective_entities(history) == {PIIEntity.IP_ADDRESS}

    def test_both_none_yields_empty_set(self):
        """Yield an empty set when no mask is configured anywhere (no PII scrubbing)."""
        assert _effective_entities(self._history(None, None)) == set()


class TestBuildOwnerAlertDetails:
    """Test ``build_owner_alert_details`` orchestration edge cases."""

    @staticmethod
    def _archiver_history(*, exec_meta, task_data, target="executor-host"):
        """Return a stub ARCHIVER history for the detail builder."""
        return SimpleNamespace(
            id=42,
            task=SimpleNamespace(owner="ARCHIVER", data=task_data, anonymize_mask=None),
            execution_request=SimpleNamespace(meta=exec_meta, target=target),
            anonymize_mask=None,
        )

    @pytest.mark.asyncio
    async def test_falls_back_to_task_data_meta_when_snapshot_empty(self, mocker):
        """Fall back to task.data meta when the execution snapshot meta is empty.

        Covers legacy histories whose ``execution_request.meta`` is empty: the
        builder reads ``task.data["meta"]`` so source node + config still render.
        """
        mocker.patch(
            "app.sep.apps.archives.alerts._read_last_stderr",
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
        """Use the placeholder when a STDERR read fails; never abort the alert.

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
