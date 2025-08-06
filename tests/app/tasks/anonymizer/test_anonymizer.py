"""Define tests for the app.tasks.anonymizer.anonymize module."""

from unittest.mock import Mock

import pytest

from app.tasks.anonymizer import anonymize_text, PIIEntity


@pytest.fixture
def mock_analyzer(mocker) -> Mock:
    """Mock the analyzer engine."""
    return mocker.patch("app.tasks.anonymizer.anonymize.analyzer")


@pytest.fixture
def mock_anonymizer(mocker) -> Mock:
    """Mock the analyzer engine."""
    return mocker.patch("app.tasks.anonymizer.anonymize.anonymizer")


def test_anonymize_text_with_multiple_entities(mock_analyzer, mock_anonymizer):
    """Test anonymizing text with multiple entity types."""
    mock_analyzer.analyze.return_value = [
        Mock(entity_type="CREDIT_CARD"),
        Mock(entity_type="EMAIL_ADDRESS"),
    ]
    mock_anonymizer.anonymize.return_value = Mock(
        text="Log with [CREDIT_CARD] and [EMAIL_ADDRESS]"
    )

    text = "Log with 4111-1111-1111-1111 and user@example.com"
    result = anonymize_text(text, {PIIEntity.CREDIT_CARD, PIIEntity.EMAIL_ADDRESS})

    assert result == "Log with [CREDIT_CARD] and [EMAIL_ADDRESS]"
    mock_analyzer.analyze.assert_called_once()
    mock_anonymizer.anonymize.assert_called_once()


def test_anonymize_text_with_no_entities(mock_analyzer, mock_anonymizer):
    """Test anonymizing text with no entity types."""
    text = "Log without PII"
    result = anonymize_text(text, set())

    assert result == "Log without PII"
    mock_analyzer.analyze.assert_not_called()
    mock_anonymizer.anonymize.assert_not_called()


def test_anonymize_text_no_entities_found(mock_analyzer, mock_anonymizer):
    """Test anonymizing text when no entities are found."""
    mock_analyzer.analyze.return_value = []
    text = "Log with no PII"
    result = anonymize_text(text, {PIIEntity.CREDIT_CARD})

    assert result == "Log with no PII"
    mock_analyzer.analyze.assert_called_once()
    mock_anonymizer.anonymize.assert_not_called()
