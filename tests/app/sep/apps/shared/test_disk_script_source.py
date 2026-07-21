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

"""Cover the disk-backed ``ScriptSource`` factory against real script files.

The factory bridges a disk-backed :class:`~app.sep.snippets.models.snippet.BaseSnippet`
subclass onto the framework ``ScriptSource`` seam. The suite writes real ``.sh`` /
``.py`` files with ``# ---`` frontmatter into a per-test directory, points a
throwaway ``BaseSnippet`` subclass' ``BASE_DIR`` at it, and exercises the public
source hooks (``load_script`` / ``list_scripts`` / ``build_form_schema`` /
``build_execution_meta``) — mirroring the snippets ``test_script_source.py`` but
without a database, since a scaffolded script app loads its catalogue from disk.
"""

from pathlib import Path

import pytest
from starlette.datastructures import URL

from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPNotFoundException,
    HTTPUnprocessableEntityException,
)
from app.sep.apps.framework.schema import (
    BoolField,
    ChoiceField,
    HostField,
    IntegerField,
    StringField,
)
from app.sep.apps.framework.script_source import ScriptExecuteWrite, ScriptSource
from app.sep.apps.shared.disk_script_source import (
    build_disk_script_source,
    DiskScriptListRow,
)
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.models.snippet import BaseSnippet, SnippetExecutionMeta

pytestmark = pytest.mark.asyncio


_SHELL_NO_PARAMS = """#!/usr/bin/env bash
# ---
# title: Bare
# ---
echo "hi"
"""

_SHELL_MESSAGE_PARAM = """#!/usr/bin/env bash
# ---
# title: Greeter
# parameters:
#   - name: message
#     label: Message
#     positional: true
# ---
echo "${1:-}"
"""

_SHELL_TYPED_PARAMS = """#!/usr/bin/env bash
# ---
# title: Typed
# parameters:
#   - name: mode
#     label: Mode
#     choices:
#       - value: fast
#       - value: slow
#   - name: retries
#     label: Retries
#     type: int
#   - name: verbose
#     label: Verbose
#     type: bool
# ---
echo "run"
"""

_SHELL_OPTIONAL_SUDO = """#!/usr/bin/env bash
# ---
# title: Sudoable
# sudo: optional
# ---
echo "hi"
"""

_SHELL_REQUIRES_GATE = """#!/usr/bin/env bash
# ---
# title: Gated
# parameters:
#   - name: mode
#     label: Mode
#   - name: reason
#     label: Reason
#     requires_when:
#       parameter: mode
#       equals: write
# ---
echo "run"
"""

_SHELL_INVALID_PARAM = """#!/usr/bin/env bash
# ---
# title: Broken
# parameters:
#   - name: mode
#     label: Mode
#     visible_when:
#       parameter: nonexistent
#       equals: x
# ---
echo "run"
"""

_PYTHON_NO_REQS = """#!/usr/bin/env python3
# ---
# title: Plain Python
# ---
print("hi")
"""

_PYTHON_WITH_REQS = """#!/usr/bin/env python3
# ---
# title: Python With Reqs
# requires_packages:
#   - requests
# ---
print("hi")
"""


def _write_script(script_dir: Path, filename: str, content: str) -> str:
    """Write ``content`` to ``filename`` under ``script_dir`` and return the filename."""
    (script_dir / filename).write_text(content)
    return filename


def _framework_processed_body(
    source: ScriptSource, script: object, body: ScriptExecuteWrite
) -> ScriptExecuteWrite:
    """Reproduce the seam's pre-processing (validate ``args`` -> coerced dump).

    ``derive_script_routes`` validates ``body.args`` against the script's args-only
    model and replaces them with the coerced ``model_dump()`` before the
    ``build_execution_meta`` hook runs, so a direct hook call must reproduce it.
    """
    validated = script.get_execution_model().model_validate(body.args)
    return body.model_copy(update={"args": validated.model_dump()})


def _fields(schema: object) -> dict[str, object]:
    """Return every form field across a schema's sections, keyed by field name."""
    return {field.name: field for section in schema.forms for field in section.fields}


@pytest.fixture
def script_dir(tmp_path: Path) -> Path:
    """Return an empty per-test script directory."""
    directory = tmp_path / "snippets"
    directory.mkdir()
    return directory


@pytest.fixture
def source(script_dir: Path, monkeypatch: pytest.MonkeyPatch) -> ScriptSource:
    """Build a disk-backed source over a throwaway ``BaseSnippet`` subclass."""
    monkeypatch.setattr(
        snippets_settings, "SNIPPETS_BASE_URL", URL("https://sep.example")
    )

    class _KitScript(BaseSnippet):
        BASE_DIR = script_dir

    return build_disk_script_source(
        script_dir=script_dir,
        script_cls=_KitScript,
        artifact_type="testkit",
        name="testkit",
        display_name="Test Kit",
    )


class TestLoadAndList:
    """Cover disk resolution and listing."""

    async def test_missing_script_raises_404(self, source: ScriptSource) -> None:
        """Raise 404 when the requested script file is absent from the directory."""
        with pytest.raises(HTTPNotFoundException):
            await source.load_script("nope.sh")

    async def test_load_script_returns_usable_adapter(
        self, source: ScriptSource, script_dir: Path
    ) -> None:
        """Resolve a written script to an adapter exposing filename and task name."""
        _write_script(script_dir, "ok.sh", _SHELL_NO_PARAMS)
        script = await source.load_script("ok.sh")
        assert script.filename == "ok.sh"
        assert script.execution_task_name == "exec-artifact"

    async def test_list_scripts_returns_every_file(
        self, source: ScriptSource, script_dir: Path
    ) -> None:
        """Return one list row per discovered file, projected to the row model."""
        _write_script(script_dir, "a.sh", _SHELL_NO_PARAMS)
        _write_script(script_dir, "b.sh", _SHELL_NO_PARAMS)
        scripts = await source.list_scripts()
        rows = [source.list_response(script) for script in scripts]
        assert all(isinstance(row, DiskScriptListRow) for row in rows)
        assert sorted(row.filename for row in rows) == ["a.sh", "b.sh"]


class TestTaskAndInterpreterDerivation:
    """Cover runtime task/interpreter derivation from the script's extension/reqs."""

    async def test_shell_script_dispatches_exec_artifact_under_bash(
        self, source: ScriptSource, script_dir: Path
    ) -> None:
        """Derive ``exec-artifact`` + ``bash`` for a shell script with no requirements."""
        _write_script(script_dir, "ok.sh", _SHELL_NO_PARAMS)
        script = await source.load_script("ok.sh")
        assert script.execution_task_name == "exec-artifact"
        body = ScriptExecuteWrite(executor_host="exec-1", args={})
        meta = source.build_execution_meta(
            script, _framework_processed_body(source, script, body)
        )
        assert meta.interpreter == "bash"

    async def test_plain_python_dispatches_exec_artifact_under_python3(
        self, source: ScriptSource, script_dir: Path
    ) -> None:
        """Derive ``exec-artifact`` + ``python3`` for a Python script with no reqs."""
        _write_script(script_dir, "ok.py", _PYTHON_NO_REQS)
        script = await source.load_script("ok.py")
        assert script.execution_task_name == "exec-artifact"
        body = ScriptExecuteWrite(executor_host="exec-1", args={})
        meta = source.build_execution_meta(
            script, _framework_processed_body(source, script, body)
        )
        assert meta.interpreter == "python3"

    async def test_python_with_requirements_dispatches_python_artifact(
        self, source: ScriptSource, script_dir: Path
    ) -> None:
        """Derive ``exec-python-artifact`` and carry the requirements into the meta."""
        _write_script(script_dir, "reqs.py", _PYTHON_WITH_REQS)
        script = await source.load_script("reqs.py")
        assert script.execution_task_name == "exec-python-artifact"
        body = ScriptExecuteWrite(executor_host="exec-1", args={})
        meta = source.build_execution_meta(
            script, _framework_processed_body(source, script, body)
        )
        assert meta.requirements == "requests"


class TestFormSchema:
    """Cover frontmatter-driven form synthesis reusing ``field_for``."""

    async def test_typed_parameters_reuse_field_for_field_types(
        self, source: ScriptSource, script_dir: Path
    ) -> None:
        """Map choice/int/bool parameters onto their framework field counterparts."""
        _write_script(script_dir, "typed.sh", _SHELL_TYPED_PARAMS)
        script = await source.load_script("typed.sh")
        fields = _fields(source.build_form_schema(script))
        assert isinstance(fields["mode"], ChoiceField)
        assert isinstance(fields["retries"], IntegerField)
        assert isinstance(fields["verbose"], BoolField)

    async def test_execution_section_carries_host_and_optional_sudo(
        self, source: ScriptSource, script_dir: Path
    ) -> None:
        """Render the executor-host field plus a sudo toggle for an optional-sudo script."""
        _write_script(script_dir, "sudo.sh", _SHELL_OPTIONAL_SUDO)
        script = await source.load_script("sudo.sh")
        fields = _fields(source.build_form_schema(script))
        assert isinstance(fields["executor_host"], HostField)
        assert isinstance(fields["sudo"], BoolField)

    async def test_script_without_parameters_has_only_execution_fields(
        self, source: ScriptSource, script_dir: Path
    ) -> None:
        """Render only the Execution section when the script declares no parameters."""
        _write_script(script_dir, "bare.sh", _SHELL_NO_PARAMS)
        script = await source.load_script("bare.sh")
        fields = _fields(source.build_form_schema(script))
        assert set(fields) == {"executor_host"}
        assert isinstance(fields["executor_host"], HostField)

    async def test_string_parameter_maps_to_string_field(
        self, source: ScriptSource, script_dir: Path
    ) -> None:
        """Map a plain string parameter onto a ``StringField``."""
        _write_script(script_dir, "msg.sh", _SHELL_MESSAGE_PARAM)
        script = await source.load_script("msg.sh")
        fields = _fields(source.build_form_schema(script))
        assert isinstance(fields["message"], StringField)


class TestExecuteMeta:
    """Cover args validation, meta assembly, sudo, and gate enforcement."""

    async def test_args_only_validation_succeeds_without_hostname(
        self, source: ScriptSource, script_dir: Path
    ) -> None:
        """Validate an args body that omits the required ``-hostname-`` field."""
        _write_script(script_dir, "ok.sh", _SHELL_NO_PARAMS)
        script = await source.load_script("ok.sh")
        validated = script.get_execution_model().model_validate({})
        assert validated.executor_host is None

    async def test_meta_assembly_signs_source_and_targets_host(
        self, source: ScriptSource, script_dir: Path
    ) -> None:
        """Assemble a meta with a signed source URL, 32-char checksum, and host target."""
        _write_script(script_dir, "ok.sh", _SHELL_NO_PARAMS)
        script = await source.load_script("ok.sh")
        body = ScriptExecuteWrite(executor_host="exec-1", args={})
        meta = source.build_execution_meta(
            script, _framework_processed_body(source, script, body)
        )
        assert isinstance(meta, SnippetExecutionMeta)
        assert meta.target == "exec-1"
        assert "/artifacts/download/" in meta.snippet_source
        assert meta.md5_checksum == script.snippet.md5_digest

    @pytest.mark.parametrize("requested_sudo", [True, False])
    async def test_optional_sudo_toggle_is_honored(
        self, source: ScriptSource, script_dir: Path, *, requested_sudo: bool
    ) -> None:
        """Apply the ``sudo`` interpreter prefix only when the caller opts in."""
        _write_script(script_dir, "sudo.sh", _SHELL_OPTIONAL_SUDO)
        script = await source.load_script("sudo.sh")
        body = ScriptExecuteWrite(executor_host="exec-1", sudo=requested_sudo, args={})
        meta = source.build_execution_meta(
            script, _framework_processed_body(source, script, body)
        )
        assert meta.interpreter.startswith("sudo ") == requested_sudo

    async def test_requires_gate_violation_raises_422(
        self, source: ScriptSource, script_dir: Path
    ) -> None:
        """Reject a submission that violates a ``requires_when`` gate with 422."""
        _write_script(script_dir, "gated.sh", _SHELL_REQUIRES_GATE)
        script = await source.load_script("gated.sh")
        body = ScriptExecuteWrite(executor_host="exec-1", args={"mode": "write"})
        with pytest.raises(HTTPUnprocessableEntityException):
            source.build_execution_meta(
                script, _framework_processed_body(source, script, body)
            )

    async def test_invalid_frontmatter_parameters_raise_400(
        self, source: ScriptSource, script_dir: Path
    ) -> None:
        """Reject a script whose frontmatter declares an invalid parameter."""
        _write_script(script_dir, "broken.sh", _SHELL_INVALID_PARAM)
        script = await source.load_script("broken.sh")
        body = ScriptExecuteWrite(executor_host="exec-1", args={})
        with pytest.raises(HTTPBadRequestException):
            source.build_execution_meta(
                script, _framework_processed_body(source, script, body)
            )

    async def test_missing_base_url_raises_400(
        self, source: ScriptSource, script_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raise 400 when neither ``SNIPPETS_BASE_URL`` nor ``BASE_URL`` is configured."""
        monkeypatch.setattr(snippets_settings, "SNIPPETS_BASE_URL", None)
        monkeypatch.setattr(
            "app.sep.apps.framework.script_helpers.settings.BASE_URL", None
        )
        _write_script(script_dir, "ok.sh", _SHELL_NO_PARAMS)
        script = await source.load_script("ok.sh")
        body = ScriptExecuteWrite(executor_host="exec-1", args={})
        with pytest.raises(HTTPBadRequestException):
            source.build_execution_meta(
                script, _framework_processed_body(source, script, body)
            )
