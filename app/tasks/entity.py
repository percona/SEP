"""Define an enumeration for sensitive data types and provide functions."""

from enum import IntEnum

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine, InvalidParamError, OperatorConfig

# Initialize Presidio engines.
analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()


class Entity(IntEnum):
    """Enumeration of sensitive data types represented as bitmask flags.

    Each member value is a bit-shifted integer that uniquely identifies a
    particular sensitive data type.
    """

    CREDIT_CARD = 1 << 0
    EMAIL_ADDRESS = 1 << 1
    IBAN_CODE = 1 << 2
    IP_ADDRESS = 1 << 3
    NRP = 1 << 4
    LOCATION = 1 << 5
    PERSON = 1 << 6
    PHONE_NUMBER = 1 << 7
    MEDICAL_LICENSE = 1 << 8
    US_BANK_NUMBER = 1 << 9
    US_DRIVER_LICENSE = 1 << 10
    US_ITIN = 1 << 11
    US_PASSPORT = 1 << 12
    US_SSN = 1 << 13


def encode_selection(selected_entities: list[Entity]) -> int:
    """Encode a list of :class:`Entity` enum members into an integer bitmask.

    :param selected_entities: A list of :class:`Entity` members to encode.
    :type selected_entities: list[Entity]
    :return: The integer bitmask representing the selected entities.
    :rtype: int
    """
    number = 0
    for entity in selected_entities:
        number |= entity.value
    return number


def decode_selection(number: int) -> list[Entity]:
    """Decode an integer bitmask into a list of :class:`Entity` enum members.

    :param number: The integer bitmask to decode.
    :type number: int
    :return: A list of :class:`Entity` members corresponding to the bitmask.
    :rtype: list[Entity]
    """
    return [entity for entity in Entity if number & entity.value]


def presidio_anonymize_log(
    log_text: str, anonymize_bitmask: int
) -> tuple[str, list[dict]]:
    """Anonymize the log text using Microsoft Presidio based on the anonymize bitmask.

    :param log_text: The original log text.
    :type log_text: str
    :param anonymize_bitmask: Bitmask indicating which entities to anonymize.
    :type anonymize_bitmask: int
    :return: A tuple containing the encrypted log text and a list of encrypted items.
    :rtype: tuple[str, list[dict]]
    """
    from app.tasks.config import tasks_settings

    # Decode the bitmask into a list of Entity enum members.
    selected_entities = decode_selection(anonymize_bitmask)

    # Use each entity's name directly as the PII type.
    pii_types = [entity.name for entity in selected_entities]

    all_results = []
    for pii_type in pii_types:
        results = analyzer.analyze(text=log_text, entities=[pii_type], language="en")
        all_results.extend(results)

    # Configure anonymization for each detected PII type.
    anonymizers_config = {
        result.entity_type: OperatorConfig(
            "encrypt", {"key": tasks_settings.SECRET_KEY}
        )
        for result in all_results
    }

    try:
        anonymized_result = anonymizer.anonymize(
            text=log_text, analyzer_results=all_results, operators=anonymizers_config
        )
    except InvalidParamError as ipe:
        raise ValueError(
            f"Invalid parameter error in presidio_encrypt_log: {ipe}"
        ) from ipe

    return anonymized_result.text, anonymized_result.items
