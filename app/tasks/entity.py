"""Define an enumeration for sensitive data types and provide functions."""

from enum import IntEnum


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
    API_KEY = 1 << 14


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
