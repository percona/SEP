"""Define tests for the app.tasks.anonymizer module."""

from unittest.mock import Mock

import pytest

from app.tasks.anonymizer import (
    AnonymizerEntity,
    decode_selection,
    encode_selection,
    presidio_anonymize_log,
)


@pytest.mark.parametrize(
    "original_entities",
    [
        set(),
        {AnonymizerEntity.EMAIL_ADDRESS},
        {
            AnonymizerEntity.CREDIT_CARD,
            AnonymizerEntity.IP_ADDRESS,
            AnonymizerEntity.PERSON,
        },
        set(AnonymizerEntity),
    ],
)
def test_encode_decode_round_trip(original_entities):
    """Test that encode then decode returns the original entities."""
    encoded = encode_selection(original_entities)
    decoded = decode_selection(encoded)
    assert set(decoded) == original_entities


def test_presidio_anonymize_log_with_multiple_entities(mocker):
    """Test anonymizing log text with multiple entity types."""
    mock_analyzer = mocker.patch("app.tasks.anonymizer.analyzer")
    mock_anonymizer = mocker.patch("app.tasks.anonymizer.anonymizer")

    mock_result1 = Mock()
    mock_result1.entity_type = "CREDIT_CARD"
    mock_result2 = Mock()
    mock_result2.entity_type = "EMAIL_ADDRESS"
    mock_analyzer.analyze.side_effect = [[mock_result1], [mock_result2]]

    mock_anonymized_result = Mock()
    mock_anonymized_result.text = "Log with [CREDIT_CARD] and [EMAIL_ADDRESS]"
    mock_anonymizer.anonymize.return_value = mock_anonymized_result

    log_text = "Log with 4111-1111-1111-1111 and user@example.com"
    bitmask = encode_selection(
        {AnonymizerEntity.CREDIT_CARD, AnonymizerEntity.EMAIL_ADDRESS}
    )
    result = presidio_anonymize_log(log_text, bitmask)

    assert result == "Log with [CREDIT_CARD] and [EMAIL_ADDRESS]"
    mock_anonymizer.anonymize.assert_called_once()


def test_presidio_anonymize_log_presidio_error(mocker):
    """Test that Presidio errors are properly handled and converted to ValueError."""
    from presidio_anonymizer import InvalidParamError

    mock_analyzer = mocker.patch("app.tasks.anonymizer.analyzer")
    mock_anonymizer = mocker.patch("app.tasks.anonymizer.anonymizer")

    mock_analyzer.analyze.return_value = []
    mock_anonymizer.anonymize.side_effect = InvalidParamError("Test error")

    log_text = "Test log"
    bitmask = encode_selection({AnonymizerEntity.CREDIT_CARD})

    with pytest.raises(
        ValueError, match="Invalid parameter error in presidio_encrypt_log: Test error"
    ):
        presidio_anonymize_log(log_text, bitmask)


def test_presidio_anonymize_log_operator_config_creation(mocker):
    """Test that OperatorConfig is created correctly for each detected entity."""
    from presidio_anonymizer import OperatorConfig

    mock_analyzer = mocker.patch("app.tasks.anonymizer.analyzer")
    mock_anonymizer = mocker.patch("app.tasks.anonymizer.anonymizer")

    mock_result1 = Mock()
    mock_result1.entity_type = "CREDIT_CARD"
    mock_result2 = Mock()
    mock_result2.entity_type = "EMAIL_ADDRESS"
    mock_analyzer.analyze.side_effect = [[mock_result1], [mock_result2]]

    mock_anonymized_result = Mock()
    mock_anonymized_result.text = "Anonymized text"
    mock_anonymizer.anonymize.return_value = mock_anonymized_result

    log_text = "Test log"
    bitmask = encode_selection(
        {AnonymizerEntity.CREDIT_CARD, AnonymizerEntity.EMAIL_ADDRESS}
    )
    presidio_anonymize_log(log_text, bitmask)

    call_args = mock_anonymizer.anonymize.call_args
    operators = call_args[1]["operators"]

    assert "CREDIT_CARD" in operators
    assert "EMAIL_ADDRESS" in operators
    assert isinstance(operators["CREDIT_CARD"], OperatorConfig)
    assert isinstance(operators["EMAIL_ADDRESS"], OperatorConfig)
    assert operators["CREDIT_CARD"].operator_name == "replace"
    assert operators["EMAIL_ADDRESS"].operator_name == "replace"
