"""Tests for snippet utility functions."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.sep.snippets.utils import generate_unique_identifiers, guess_mime_type

EXPECTED_TWO_CHAR_ID_LENGTH = 2


class TestGuessMimeType:
    """Test the guess_mime_type function."""

    def test_known_extension_without_magic(self):
        """Verify correct MIME type for known file extension using mimetypes."""
        result = guess_mime_type(Path("script.sh"))
        assert result in ("text/x-sh", "application/x-sh")

    def test_python_extension_without_magic(self):
        """Verify correct MIME type for .py extension using mimetypes."""
        result = guess_mime_type(Path("script.py"))
        assert result == "text/x-python"

    def test_unknown_extension_returns_text_plain(self):
        """Verify unknown extension returns text/plain as default."""
        result = guess_mime_type(Path("file.xyznonexistent"))
        assert result == "text/plain"

    def test_with_magic_enabled(self, tmp_path):
        """Verify MIME type detection using python-magic when enabled."""
        import sys

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        mock_magic = MagicMock()
        mock_magic.from_file.return_value = "text/plain"
        sys.modules["magic"] = mock_magic

        try:
            with patch("app.sep.snippets.utils.snippets_settings") as mock_settings:
                mock_settings.USE_MAGIC = True
                guess_mime_type.__wrapped__(test_file)
                mock_magic.from_file.assert_called_once_with(test_file, mime=True)
        finally:
            del sys.modules["magic"]

    def test_magic_returns_none_falls_back_to_text_plain(self, tmp_path):
        """Verify fallback to text/plain when magic returns None."""
        import sys

        test_file = tmp_path / "test.dat"
        test_file.write_bytes(b"\x00\x00")

        mock_magic = MagicMock()
        mock_magic.from_file.return_value = None
        sys.modules["magic"] = mock_magic

        try:
            with patch("app.sep.snippets.utils.snippets_settings") as mock_settings:
                mock_settings.USE_MAGIC = True
                result = guess_mime_type.__wrapped__(test_file)
                assert result == "text/plain"
        finally:
            del sys.modules["magic"]


class TestGenerateUniqueIdentifiers:
    """Test the generate_unique_identifiers generator."""

    def test_first_52_are_single_letters(self):
        """Verify first 52 identifiers are single letters a-z, A-Z."""
        gen = generate_unique_identifiers()
        first_52 = [next(gen) for _ in range(52)]
        assert first_52[:26] == list("abcdefghijklmnopqrstuvwxyz")
        assert first_52[26:] == list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

    def test_identifiers_are_valid_python(self):
        """Verify generated identifiers are valid Python identifiers."""
        gen = generate_unique_identifiers()
        for _ in range(200):
            identifier = next(gen)
            assert identifier.isidentifier(), (
                f"{identifier!r} is not a valid identifier"
            )

    def test_identifiers_after_single_chars(self):
        """Verify identifiers after single chars have correct format."""
        gen = generate_unique_identifiers()
        for _ in range(52):
            next(gen)
        next_id = next(gen)
        assert len(next_id) == EXPECTED_TWO_CHAR_ID_LENGTH
        assert next_id[0].isalpha()
        assert next_id[-1].isdigit()

    def test_no_duplicates_in_first_500(self):
        """Verify no duplicate identifiers in first 500 generated."""
        gen = generate_unique_identifiers()
        identifiers = [next(gen) for _ in range(500)]
        assert len(identifiers) == len(set(identifiers))
