"""Define tests for the app.core.utils.strings module."""

from base64 import b64encode

from app.core.utils.strings import b64encode_str, slugify


def test_slugify():
    """Test slugify utility for various input cases."""
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("  Python@3.8  ") == "python-3-8"
    assert slugify("Café Münchén") == "cafe-munchen"
    assert slugify("___") == ""
    assert slugify("") == ""
    assert slugify("No_Special-Characters") == "no-special-characters"


def test_b64encode_str():
    """Test b64encode_str utility for base64 encoding strings."""
    assert b64encode_str("hello") == "aGVsbG8="
    assert b64encode_str("") == ""

    encoded = b64encode_str("café", encoding="latin-1")
    assert encoded == b64encode("café".encode("latin-1")).decode("latin-1")
