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

"""Define tests for the app.sep.apps.mysql_backups.restore.models module."""

import pytest
from pydantic import ValidationError

from app.sep.apps.framework.form_dsl.derivation import derive_form_sections
from app.sep.apps.framework.schema import ChoiceField, RemoteChoiceField
from app.sep.apps.mysql_backups.forms import EncryptionFormat
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.restore.models import (
    normalize_source_declaration,
    RestoreConfigAll,
    RestoreConfigServer,
    RestoreCreate,
    S3Tool,
    SourceTransport,
)
from app.sep.apps.mysql_backups.restore.views import restore_views


def _minimal_restore_create_body(**overrides: object) -> dict:
    """Return a minimal valid :class:`RestoreCreate` payload."""
    body = {
        "task_name": "restore-1",
        "hostname": "executor-1",
        "backup_type": BackupType.MYDUMPER,
        "backup_source": "/var/backups/latest",
    }
    body.update(overrides)
    return body


def test_backup_source_is_remote_choice_cascading_on_service_id() -> None:
    """Derive backup_source as a RemoteChoices field cascading on service_id."""
    sections = derive_form_sections(RestoreCreate, restore_views.layout)
    fields_by_section = {
        section.title: {field.name: field for field in section.fields}
        for section in sections
    }
    backup_source = fields_by_section["Task"]["backup_source"]
    assert isinstance(backup_source, RemoteChoiceField)
    assert backup_source.endpoint_url == "/apps/mysql_backups/backup-sources/choices"
    assert backup_source.depends_on == "service_id"
    assert backup_source.allow_custom is True
    assert "service_id" in fields_by_section["Task"]
    assert "service_id" not in fields_by_section["Mydumper"]


def test_restore_create_coerces_int_reference_ids_to_str() -> None:
    """Accept JSON inventory ids as ints (React schema form) by stringifying."""
    model = RestoreCreate.model_validate(
        _minimal_restore_create_body(service_id=4, schema_id=11)
    )
    assert model.service_id == "4"
    assert model.schema_id == "11"


def test_restore_create_preserves_str_reference_ids() -> None:
    """Leave str-typed reference ids unchanged (Jinja / legacy form path)."""
    model = RestoreCreate.model_validate(
        _minimal_restore_create_body(service_id="4", schema_id="11")
    )
    assert model.service_id == "4"
    assert model.schema_id == "11"


def _server_with_backup_source(backup_source: str) -> dict:
    return {
        "alias": "a",
        "backup_type": BackupType.MYDUMPER,
        "backup_source": backup_source,
        "datadir": "/var/lib/mysql",
    }


@pytest.mark.parametrize(
    "backup_source",
    [
        "host:/backups/foo/latest",
        "/var/backups/latest",
        "10.0.0.1:/data/mysql_backup/latest",
    ],
)
def test_validate_backup_source_accepts_safe_paths(backup_source: str) -> None:
    """Accept typical host:path and local paths without shell metacharacters."""
    RestoreConfigServer.model_validate(_server_with_backup_source(backup_source))


@pytest.mark.parametrize(
    ("backup_source", "error_match"),
    [
        # Advisory PoC: host looks like latest symlink path; $(...) was evaluated by bash.
        ("$(id>/tmp/pwned):foo/latest", "shell metacharacters"),
        ("$(id)", "shell metacharacters"),
        ("`id`", "shell metacharacters"),
        ("host:/path;rm -rf /", "shell metacharacters"),
        ("a|b", "shell metacharacters"),
        ("a&b", "shell metacharacters"),
        ("a;b", "shell metacharacters"),
        ("foo$(bar)", "shell metacharacters"),
        ("bad\nline", "newline"),
        ("bad\rline", "newline"),
    ],
)
def test_validate_backup_source_rejects_unsafe_input(
    backup_source: str,
    error_match: str,
) -> None:
    """Reject newlines and shell metacharacters per field validator.

    Includes the documented restore-form PoC (``$(id>/tmp/pwned):foo/latest``), which
    previously led to command substitution in a shell-wrapped ``ssh`` invocation.
    """
    with pytest.raises(ValidationError, match=error_match):
        RestoreConfigServer.model_validate(_server_with_backup_source(backup_source))


def _derived_fields() -> dict:
    """Return every derived form field keyed by name, across all sections."""
    sections = derive_form_sections(RestoreCreate, restore_views.layout)
    return {field.name: field for section in sections for field in section.fields}


def test_source_controls_are_always_visible_task_choices() -> None:
    """Declare both source controls as ungated choice fields in the Task section.

    They decide what else renders, so they cannot sit in ``General``, which is
    collapsed by default, nor carry gates of their own.
    """
    sections = derive_form_sections(RestoreCreate, restore_views.layout)
    task_fields = {
        field.name: field
        for section in sections
        if section.title == "Task"
        for field in section.fields
    }

    for name in ("source_transport", "source_encryption"):
        assert isinstance(task_fields[name], ChoiceField), name
        assert task_fields[name].forbidden is None, name


def test_only_the_transport_and_decryption_fields_are_gated() -> None:
    """Gate exactly the five fields a source declaration governs, and nothing else.

    The predicates themselves are pinned on the served schema in
    ``test_schema_gates_transport_and_decryption_fields``; what matters here is
    that no other field acquired a gate, since every gated field also had to give
    up its default.
    """
    gated = {name for name, field in _derived_fields().items() if field.forbidden}

    assert gated == {
        "ssh_user",
        "ssh_port",
        "ssh_key",
        "s3_tool",
        "gpg_password_file",
    }


@pytest.mark.parametrize("field_name", ["ssh_user", "ssh_port", "s3_tool"])
def test_gated_fields_default_to_none(field_name: str) -> None:
    """Default every gated field to ``None`` so its own gate cannot reject it.

    A field-level ``Forbidden`` rejects a field that is *present*, and a non-``None``
    default is present, so leaving ``percona`` / ``22`` / ``s3cmd`` in place would
    422 every restore that does not declare the matching transport.
    """
    assert RestoreCreate.model_fields[field_name].default is None
    assert _derived_fields()[field_name].default is None


def test_local_restore_validates_without_transport_fields() -> None:
    """Accept a local restore that declares neither SSH nor object-store values."""
    model = RestoreCreate.model_validate(
        _minimal_restore_create_body(source_transport=SourceTransport.LOCAL)
    )

    assert model.ssh_user is None
    assert model.ssh_port is None
    assert model.s3_tool is None


def test_declared_transport_rejects_a_field_it_forbids() -> None:
    """Reject a body whose declared transport forbids a field it still sends.

    This is the server-side teeth of the gates: a client that hides the field
    must not be able to submit it anyway.
    """
    with pytest.raises(ValidationError, match="'ssh_user' must not be set"):
        RestoreCreate.model_validate(
            _minimal_restore_create_body(
                source_transport=SourceTransport.LOCAL, ssh_user="deploy"
            )
        )


def test_declared_encryption_rejects_gpg_password_file() -> None:
    """Reject a GPG password file on a restore declaring no GPG pass."""
    with pytest.raises(ValidationError, match="'gpg_password_file' must not be set"):
        RestoreCreate.model_validate(
            _minimal_restore_create_body(
                source_encryption=EncryptionFormat.NONE,
                gpg_password_file="/etc/gpg.pass",
            )
        )


def test_empty_s3_tool_does_not_trip_its_gate() -> None:
    """Coerce a cleared ``s3_tool`` select to ``None`` rather than tripping its gate."""
    model = RestoreCreate.model_validate(
        _minimal_restore_create_body(source_transport=SourceTransport.LOCAL, s3_tool="")
    )

    assert model.s3_tool is None


def _legacy_default(field_name: str) -> object:
    """Return a gated field's pre-declaration default, read from the config model.

    The config models still declare ``percona`` / ``22`` / ``s3cmd``, so reading
    them here keeps the tests from carrying a second copy of the table the
    normalizer itself derives.
    """
    default = RestoreConfigAll.model_fields[field_name].default
    return default.value if isinstance(default, S3Tool) else default


def _legacy_stamp(**overrides: object) -> dict:
    """Return a full pre-declaration stamp, as ``stamp_form_input`` would have dumped it."""
    stamp = {
        "task_name": "restore-1",
        "hostname": "executor-1",
        "backup_type": BackupType.MYDUMPER.value,
        "backup_source": "/var/backups/latest",
        "ssh_user": _legacy_default("ssh_user"),
        "ssh_port": _legacy_default("ssh_port"),
        "ssh_key": None,
        "s3_tool": _legacy_default("s3_tool"),
        "gpg_password_file": None,
    }
    stamp.update(overrides)
    return stamp


@pytest.mark.parametrize(
    ("overrides", "expected_transport", "expected_survivors", "expected_dropped"),
    [
        pytest.param(
            {},
            SourceTransport.LOCAL,
            {},
            ("ssh_user", "ssh_port", "s3_tool"),
            id="local-source-drops-every-default",
        ),
        pytest.param(
            {"ssh_key": "prod-key"},
            SourceTransport.SSH,
            {"ssh_key": "prod-key"},
            ("s3_tool",),
            id="ssh-key-implies-ssh",
        ),
        pytest.param(
            {"ssh_user": "deploy"},
            SourceTransport.SSH,
            {"ssh_user": "deploy"},
            ("s3_tool",),
            id="non-default-ssh-user-implies-ssh",
        ),
        pytest.param(
            {"backup_source": "gs://bucket/path", "s3_tool": "awscli"},
            SourceTransport.GCS,
            {},
            ("ssh_user", "ssh_port", "s3_tool"),
            id="gcs-scheme-wins-over-ssh-credentials-and-drops-the-s3-tool",
        ),
        pytest.param(
            {"backup_source": "db01:/backups/mydumper"},
            SourceTransport.SSH,
            {},
            ("s3_tool",),
            id="host-colon-path-implies-ssh",
        ),
        pytest.param(
            {
                "backup_source": "s3://bucket/path",
                "ssh_user": "deploy",
                "ssh_port": 2222,
                "ssh_key": "prod-key",
                "s3_tool": "awscli",
            },
            SourceTransport.S3,
            {"s3_tool": "awscli"},
            ("ssh_user", "ssh_port", "ssh_key"),
            id="s3-scheme-drops-contradicting-ssh-credentials",
        ),
        pytest.param(
            {"ssh_user": "deploy", "s3_tool": "awscli"},
            SourceTransport.SSH,
            {"ssh_user": "deploy"},
            ("s3_tool",),
            id="local-source-with-credentials-drops-contradicting-s3-tool",
        ),
    ],
)
def test_normalize_source_declaration_infers_and_strips(
    overrides: dict,
    expected_transport: SourceTransport,
    expected_survivors: dict,
    expected_dropped: tuple[str, ...],
) -> None:
    """Infer the transport a legacy stamp implies and drop what that transport forbids."""
    normalized = normalize_source_declaration(_legacy_stamp(**overrides))

    assert normalized["source_transport"] == expected_transport
    for name, value in expected_survivors.items():
        assert normalized[name] == value
    for name in expected_dropped:
        assert name not in normalized


@pytest.mark.parametrize(
    ("overrides", "expected_encryption"),
    [
        ({}, EncryptionFormat.NONE),
        ({"gpg_password_file": "/etc/gpg.pass"}, EncryptionFormat.GPG),
        (
            {
                "backup_type": BackupType.XTRABACKUP.value,
                "xtrabackup_aes256_keyfile": "/etc/aes.key",
            },
            EncryptionFormat.AES256,
        ),
        (
            {
                "backup_type": BackupType.XTRABACKUP.value,
                "xtrabackup_aes256_keyfile": "/etc/aes.key",
                "gpg_password_file": "/etc/gpg.pass",
            },
            EncryptionFormat.DUAL,
        ),
    ],
)
def test_normalize_source_declaration_infers_encryption(
    overrides: dict, expected_encryption: EncryptionFormat
) -> None:
    """Infer the encryption a legacy stamp ran from the passes its fields imply."""
    normalized = normalize_source_declaration(_legacy_stamp(**overrides))

    assert normalized["source_encryption"] == expected_encryption
    if expected_encryption in (EncryptionFormat.GPG, EncryptionFormat.DUAL):
        assert normalized["gpg_password_file"] == "/etc/gpg.pass"
    else:
        assert "gpg_password_file" not in normalized


def test_normalize_source_declaration_infers_only_the_missing_half() -> None:
    """Infer the encryption of a body that declares its transport and nothing else.

    The two declarations are independent: inferring one must not re-derive the
    other, or a caller that named only its transport would have an encryption
    choice made for it and the field that choice governs stripped.
    """
    declared = _legacy_stamp(
        source_transport=SourceTransport.SSH.value,
        ssh_user="deploy",
        gpg_password_file="/etc/gpg.pass",
    )

    normalized = normalize_source_declaration(declared)

    assert normalized["source_transport"] == SourceTransport.SSH.value
    assert normalized["source_encryption"] == EncryptionFormat.GPG
    assert normalized["gpg_password_file"] == "/etc/gpg.pass"
    assert normalized["ssh_user"] == "deploy"


def test_normalize_source_declaration_leaves_a_declared_stamp_alone() -> None:
    """Treat an operator's own declaration as authoritative, stripping nothing."""
    declared = _legacy_stamp(
        source_transport=SourceTransport.SSH.value,
        source_encryption=EncryptionFormat.NONE.value,
        ssh_user="deploy",
    )

    normalized = normalize_source_declaration(declared)

    assert normalized == declared


@pytest.mark.parametrize(
    ("overrides", "expected_transport"),
    [
        ({}, SourceTransport.LOCAL),
        ({"ssh_key": "prod-key"}, SourceTransport.SSH),
        (
            {"backup_source": "s3://bucket/path", "s3_tool": "awscli"},
            SourceTransport.S3,
        ),
    ],
)
def test_pre_declaration_stamp_validates_through_the_before_validator(
    overrides: dict, expected_transport: SourceTransport
) -> None:
    """Accept a full pre-declaration stamp on the edit round-trip without a backfill run.

    Every stored stamp is a full model dump carrying the old defaults, and the
    derived ``PUT`` re-submits it verbatim, so the model has to normalize an
    undeclared body itself rather than waiting for the manual backfill command.
    """
    model = RestoreCreate.model_validate(_legacy_stamp(**overrides))

    assert model.source_transport == expected_transport


def test_declared_stamp_keeps_its_gate_teeth_through_the_before_validator() -> None:
    """Reject a gate violation from a declaring client instead of silently stripping it."""
    with pytest.raises(ValidationError, match="'ssh_user' must not be set"):
        RestoreCreate.model_validate(
            _legacy_stamp(
                source_transport=SourceTransport.LOCAL.value, ssh_user="deploy"
            )
        )
