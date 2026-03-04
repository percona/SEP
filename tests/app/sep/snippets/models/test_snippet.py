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

"""Tests for BaseSnippet and Snippet models."""

from pathlib import Path
from unittest.mock import AsyncMock, patch, PropertyMock

import pytest

from app.sep.snippets.config import (
    DEFAULT_SNIPPETS_TASK,
    SnippetInterpreterConfig,
    snippets_settings,
    SnippetSudoOption,
)
from app.sep.snippets.models.snippet import BaseSnippet, BaseSnippetArgs, Snippet

EXPECTED_PARAM_COUNT = 2
UPDATED_SIZE = 200
MD5_DIGEST_LENGTH = 32


@pytest.fixture
def sample_snippet_file(tmp_path):
    """Create a temporary snippet file with YAML frontmatter."""
    content = (
        "# ---\n"
        "# title: Test Snippet\n"
        "# description: A test snippet for unit testing\n"
        "# parameters:\n"
        "#   - name: host\n"
        "#     type: str\n"
        "#     required: true\n"
        "# ---\n"
        "echo 'hello'\n"
    )
    snippet_file = tmp_path / "test_snippet.sh"
    snippet_file.write_text(content)
    return snippet_file


@pytest.fixture
def sample_snippet_no_frontmatter(tmp_path):
    """Create a temporary snippet file without frontmatter."""
    content = "echo 'hello world'\n"
    snippet_file = tmp_path / "plain_snippet.sh"
    snippet_file.write_text(content)
    return snippet_file


class TestGetMetaByPath:
    """Test the get_meta_by_path static method."""

    @pytest.mark.asyncio
    async def test_with_frontmatter(self, sample_snippet_file):
        """Verify metadata extraction from file with YAML frontmatter."""
        meta = await BaseSnippet.get_meta_by_path(sample_snippet_file)
        assert meta["title"] == "Test Snippet"
        assert meta["description"] == "A test snippet for unit testing"
        assert isinstance(meta["parameters"], list)
        assert len(meta["parameters"]) == 1
        assert meta["parameters"][0]["name"] == "host"

    @pytest.mark.asyncio
    async def test_no_frontmatter(self, sample_snippet_no_frontmatter):
        """Verify empty dict returned for file without frontmatter."""
        meta = await BaseSnippet.get_meta_by_path(sample_snippet_no_frontmatter)
        assert meta == {}

    @pytest.mark.asyncio
    async def test_binary_file_returns_empty(self, tmp_path):
        """Verify empty dict returned for binary file (UnicodeDecodeError)."""
        binary_file = tmp_path / "binary.bin"
        binary_file.write_bytes(b"\x00\x01\x02\xff\xfe")
        meta = await BaseSnippet.get_meta_by_path(binary_file)
        assert meta == {}


class TestBaseSnippetProperties:
    """Test BaseSnippet cached properties."""

    def test_title_from_meta(self):
        """Verify title is extracted from meta."""
        snippet = BaseSnippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            meta={"title": "My Title"},
        )
        assert snippet.title == "My Title"

    def test_title_defaults_to_filename(self):
        """Verify title defaults to filename when not in meta."""
        snippet = BaseSnippet(filename="test.sh", size=100, md5_digest="a" * 32)
        assert snippet.title == "test.sh"

    def test_description_from_meta(self):
        """Verify description is extracted from meta."""
        snippet = BaseSnippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            meta={"description": "A useful snippet"},
        )
        assert snippet.description == "A useful snippet"

    def test_description_defaults_to_empty(self):
        """Verify description defaults to empty string."""
        snippet = BaseSnippet(filename="test.sh", size=100, md5_digest="a" * 32)
        assert snippet.description == ""

    def test_path_property(self):
        """Verify path returns full path based on BASE_DIR."""
        snippet = BaseSnippet(filename="test.sh", size=100, md5_digest="a" * 32)
        expected = Path(snippets_settings.SNIPPETS_DIR / "test.sh")
        assert snippet.path == expected

    def test_repr(self):
        """Verify __repr__ includes filename and hash."""
        snippet = BaseSnippet(filename="test.sh", size=100, md5_digest="a" * 32)
        assert "test.sh" in repr(snippet)
        assert "a" * 32 in repr(snippet)

    def test_str(self):
        """Verify __str__ returns filename."""
        snippet = BaseSnippet(filename="test.sh", size=100, md5_digest="a" * 32)
        assert str(snippet) == "test.sh"

    def test_fspath(self):
        """Verify __fspath__ returns full path string."""
        snippet = BaseSnippet(filename="test.sh", size=100, md5_digest="a" * 32)
        assert snippet.__fspath__() == str(snippets_settings.SNIPPETS_DIR / "test.sh")

    def test_allow_extra_args_from_meta(self):
        """Verify allow_extra_args is read from meta."""
        snippet = BaseSnippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            meta={"allow_extra_args": True},
        )
        assert snippet.allow_extra_args is True

    def test_allow_extra_args_defaults(self):
        """Verify allow_extra_args defaults to settings value."""
        snippet = BaseSnippet(filename="test.sh", size=100, md5_digest="a" * 32)
        assert (
            snippet.allow_extra_args == snippets_settings.META.DEFAULT_ALLOW_EXTRA_ARGS
        )

    def test_sudo_from_meta(self):
        """Verify sudo option is read from meta."""
        snippet = BaseSnippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            meta={"sudo": 1},
        )
        assert snippet.sudo == SnippetSudoOption.ALWAYS

    def test_sudo_invalid_defaults(self):
        """Verify invalid sudo value falls back to default."""
        snippet = BaseSnippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            meta={"sudo": "invalid"},
        )
        assert snippet.sudo == snippets_settings.META.DEFAULT_SUDO_OPTION

    def test_mime_type(self):
        """Verify mime_type uses guess_mime_type."""
        snippet = BaseSnippet(filename="test.sh", size=100, md5_digest="a" * 32)
        assert isinstance(snippet.mime_type, str)

    def test_requirements_with_packages(self):
        """Verify requirements returns joined package string."""
        snippet = BaseSnippet(
            filename="test.py",
            size=100,
            md5_digest="a" * 32,
            meta={"requires_packages": ["requests", "boto3"]},
        )
        assert snippet.requirements == "requests\nboto3"

    def test_requirements_without_packages(self):
        """Verify requirements returns None when no packages."""
        snippet = BaseSnippet(filename="test.py", size=100, md5_digest="a" * 32)
        assert snippet.requirements is None


class TestExecutionInterpreter:
    """Test the execution_interpreter and execution_task_name properties."""

    def test_interpreter_found(self):
        """Verify interpreter command is returned when config matches."""
        snippet = BaseSnippet(filename="test.sh", size=100, md5_digest="a" * 32)
        config = SnippetInterpreterConfig(command="bash")
        with patch.object(
            BaseSnippet,
            "_get_execution_interpreter_config",
            return_value=config,
        ):
            assert snippet.execution_interpreter == "bash"

    def test_interpreter_not_found(self):
        """Verify None is returned when no interpreter config matches."""
        snippet = BaseSnippet(filename="test.xyz", size=100, md5_digest="a" * 32)
        with patch.object(
            BaseSnippet,
            "_get_execution_interpreter_config",
            return_value=None,
        ):
            assert snippet.execution_interpreter is None

    def test_task_name_default_when_no_interpreter(self):
        """Verify default task name when no interpreter config found."""
        snippet = BaseSnippet(filename="test.xyz", size=100, md5_digest="a" * 32)
        with patch.object(
            BaseSnippet,
            "_get_execution_interpreter_config",
            return_value=None,
        ):
            assert snippet.execution_task_name == DEFAULT_SNIPPETS_TASK

    def test_task_name_with_requirements(self):
        """Verify task_with_requirements is used when snippet has packages."""
        snippet = BaseSnippet(
            filename="test.py",
            size=100,
            md5_digest="a" * 32,
            meta={"requires_packages": ["requests"]},
        )
        config = SnippetInterpreterConfig(
            command="python3", task_with_requirements="exec-python-artifact"
        )
        with patch.object(
            BaseSnippet,
            "_get_execution_interpreter_config",
            return_value=config,
        ):
            assert snippet.execution_task_name == "exec-python-artifact"

    def test_task_name_without_requirements(self):
        """Verify regular task is used when snippet has no packages."""
        snippet = BaseSnippet(filename="test.sh", size=100, md5_digest="a" * 32)
        config = SnippetInterpreterConfig(command="bash")
        with patch.object(
            BaseSnippet,
            "_get_execution_interpreter_config",
            return_value=config,
        ):
            assert snippet.execution_task_name == config.task


class TestGetExecutionModel:
    """Test the get_execution_model method."""

    def test_returns_model_class(self):
        """Verify get_execution_model returns a BaseSnippetArgs subclass."""
        snippet = BaseSnippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            meta={
                "parameters": [
                    {"name": "host", "type": "str", "required": True},
                ]
            },
        )
        model = snippet.get_execution_model()
        assert issubclass(model, BaseSnippetArgs)

    def test_model_validates_input(self):
        """Verify the generated model can validate input data."""
        snippet = BaseSnippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            meta={
                "parameters": [
                    {"name": "host", "type": "str", "required": True},
                ]
            },
        )
        model = snippet.get_execution_model()
        instance = model(**{"-hostname-": "server1", "host": "db-host"})
        assert instance.executor_host == "server1"


class TestValidatedParameters:
    """Test the validated_parameters cached property."""

    def test_all_valid_parameters(self):
        """Verify valid parameters produce no errors."""
        snippet = BaseSnippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            meta={
                "parameters": [
                    {"name": "host", "type": "str", "required": True},
                    {"name": "port", "type": "int", "default": 3306},
                ]
            },
        )
        result = snippet.validated_parameters
        assert len(result.parameters) == EXPECTED_PARAM_COUNT
        assert len(result.errors) == 0

    def test_with_invalid_parameters(self):
        """Verify invalid parameters produce error list."""
        snippet = BaseSnippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            meta={
                "parameters": [
                    {"name": "", "type": "str"},
                ]
            },
        )
        result = snippet.validated_parameters
        assert len(result.errors) > 0

    def test_no_parameters(self):
        """Verify empty parameters produce no errors."""
        snippet = BaseSnippet(filename="test.sh", size=100, md5_digest="a" * 32)
        result = snippet.validated_parameters
        assert len(result.parameters) == 0
        assert len(result.errors) == 0


class TestCanExecute:
    """Test the can_execute property."""

    def test_with_interpreter_and_valid_params(self):
        """Verify can_execute is True with interpreter and valid params."""
        snippet = BaseSnippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            meta={"parameters": [{"name": "host", "type": "str"}]},
        )
        with patch.object(
            type(snippet),
            "execution_interpreter",
            new_callable=PropertyMock,
            return_value="bash",
        ):
            assert snippet.can_execute is True

    def test_no_interpreter(self):
        """Verify can_execute is False when no interpreter is found."""
        snippet = BaseSnippet(
            filename="test.unknown",
            size=100,
            md5_digest="a" * 32,
        )
        with patch.object(
            type(snippet),
            "execution_interpreter",
            new_callable=PropertyMock,
            return_value=None,
        ):
            assert snippet.can_execute is False


class TestSnippetModel:
    """Test the Snippet model (extends BaseSnippet with DB fields)."""

    def test_is_approved_when_set(self):
        """Verify is_approved returns True when approved_at is set."""
        from app.core.utils import utc_now

        snippet = Snippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            approved_at=utc_now(),
        )
        assert snippet.is_approved is True

    def test_is_not_approved_when_none(self):
        """Verify is_approved returns False when approved_at is None."""
        snippet = Snippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            approved_at=None,
        )
        assert snippet.is_approved is False

    def test_approve_sets_fields(self):
        """Verify approve() sets approved_at, updated_by, and reason."""
        snippet = Snippet(filename="test.sh", size=100, md5_digest="a" * 32)
        snippet.approve("Security reviewed", "user-123")
        assert snippet.approved_at is not None
        assert snippet.updated_by == "user-123"
        assert snippet.reason == "Security reviewed"

    def test_remove_approval_clears_approved_at(self):
        """Verify remove_approval() sets approved_at to None."""
        from app.core.utils import utc_now

        snippet = Snippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            approved_at=utc_now(),
        )
        snippet.remove_approval("No longer valid", "user-456")
        assert snippet.approved_at is None
        assert snippet.updated_by == "user-456"
        assert snippet.reason == "No longer valid"

    def test_can_execute_requires_approval(self):
        """Verify Snippet.can_execute requires approval on top of base check."""
        snippet = Snippet(
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            approved_at=None,
        )
        with patch.object(
            BaseSnippet,
            "can_execute",
            new_callable=PropertyMock,
            return_value=True,
        ):
            assert snippet.can_execute is False

    @pytest.mark.asyncio
    async def test_update_from_snippet(self):
        """Verify update_from_snippet updates meta and removes approval."""
        from app.core.utils import utc_now

        original = Snippet(
            id=1,
            filename="test.sh",
            size=100,
            md5_digest="a" * 32,
            approved_at=utc_now(),
        )
        new_snippet = Snippet(
            filename="test.sh",
            size=UPDATED_SIZE,
            md5_digest="b" * 32,
        )
        with patch.object(
            BaseSnippet,
            "get_meta_by_path",
            new=AsyncMock(return_value={"title": "Updated"}),
        ):
            await original.update_from_snippet(new_snippet)
        assert original.id == 1
        assert original.md5_digest == "b" * 32
        assert original.size == UPDATED_SIZE
        assert original.meta == {"title": "Updated"}
        assert original.approved_at is None


class TestFromPath:
    """Test the from_path class method."""

    @pytest.mark.asyncio
    async def test_creates_snippet_from_file(self, tmp_path):
        """Verify from_path creates a snippet with correct hash and filename."""
        snippet_file = tmp_path / "hello.sh"
        snippet_file.write_text("echo hello\n")

        with patch.object(BaseSnippet, "BASE_DIR", tmp_path):
            snippet = await BaseSnippet.from_path("hello.sh")

        assert snippet.filename == "hello.sh"
        assert len(snippet.md5_digest) == MD5_DIGEST_LENGTH
        assert snippet.size > 0

    @pytest.mark.asyncio
    async def test_from_path_with_update_meta(self, tmp_path):
        """Verify from_path calls update_meta when flag is True."""
        content = "# ---\n# title: Hello Script\n# ---\necho hello\n"
        snippet_file = tmp_path / "hello.sh"
        snippet_file.write_text(content)

        with patch.object(BaseSnippet, "BASE_DIR", tmp_path):
            snippet = await BaseSnippet.from_path("hello.sh", update_meta=True)

        assert snippet.meta.get("title") == "Hello Script"


class TestRequiresPackages:
    """Test the requires_packages cached property."""

    def test_string_packages(self):
        """Verify string requires_packages is split into list."""
        snippet = BaseSnippet(
            filename="test.py",
            size=100,
            md5_digest="a" * 32,
            meta={"requires_packages": "requests boto3"},
        )
        assert snippet.requires_packages == ["requests", "boto3"]

    def test_list_packages(self):
        """Verify list requires_packages is returned as-is with normalization."""
        snippet = BaseSnippet(
            filename="test.py",
            size=100,
            md5_digest="a" * 32,
            meta={"requires_packages": ["requests", "boto3"]},
        )
        assert snippet.requires_packages == ["requests", "boto3"]

    def test_empty_packages(self):
        """Verify empty requires_packages returns empty list."""
        snippet = BaseSnippet(filename="test.py", size=100, md5_digest="a" * 32)
        assert snippet.requires_packages == []

    def test_none_packages(self):
        """Verify None requires_packages returns empty list."""
        snippet = BaseSnippet(
            filename="test.py",
            size=100,
            md5_digest="a" * 32,
            meta={"requires_packages": None},
        )
        assert snippet.requires_packages == []
