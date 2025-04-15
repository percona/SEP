"""Define tests for the app.tasks.execution.utils module."""

from app.tasks.execution.utils import minify_file_content


def test_minify_valid_python_code():
    """Test minification of valid Python code."""
    python_code = """
def foo():
    x = 1
    y = 2
    return x + y
"""
    minified_code = minify_file_content(python_code, file_ext="py")
    assert minified_code.strip() != ""
    assert "\n" not in minified_code or len(minified_code.split("\n")) == 1
    assert "def" in minified_code
    assert "return" in minified_code


def test_minify_unrelated_file_extension():
    """Test minification with a non-Python file extension."""
    text_content = "This is some plain text."
    result = minify_file_content(text_content, file_ext="txt")
    assert result == text_content


def test_minify_with_syntax_error():
    """Test that syntax errors are handled gracefully."""
    broken_python_code = "def baz()\n    print('missing colon')"
    result = minify_file_content(broken_python_code, file_ext="py")
    assert result == broken_python_code
