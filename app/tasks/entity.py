"""Define an enumeration for sensitive data types and log anonymization functions."""

from enum import IntEnum

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import (
    AnonymizerEngine,
    DeanonymizeEngine,
    InvalidParamError,
    OperatorConfig,
    OperatorResult,
)

from app.tasks.models import TaskHistory

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

    selected_entities = decode_selection(anonymize_bitmask)

    pii_types = [entity.name for entity in selected_entities]

    all_results = []
    for pii_type in pii_types:
        results = analyzer.analyze(text=log_text, entities=[pii_type], language="en")
        all_results.extend(results)

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


def presidio_decrypt_log(anonymized_text: str, anonymized_items: list[dict]) -> str:
    """Decrypt previously anonymized log text.

    :param anonymized_text: The anonymized log text.
    :type anonymized_text: str
    :param anonymized_items: List of anonymized entities from the anonymization step.
    :type anonymized_items: List[Dict]
    :return: The decrypted log text.
    :rtype: str
    """
    if not anonymized_items:
        return anonymized_text
    from app.tasks.config import tasks_settings

    crypto_key = tasks_settings.SECRET_KEY
    deanonymize_engine = DeanonymizeEngine()
    operators_config = {"DEFAULT": OperatorConfig("decrypt", {"key": crypto_key})}
    try:
        deanonymized_result = deanonymize_engine.deanonymize(
            text=anonymized_text,
            entities=[OperatorResult(**result) for result in anonymized_items],
            operators=operators_config,
        )
    except TypeError as e:
        raise ValueError(f"Error during presidio decryption: {e}") from e

    return deanonymized_result.text


def decrypt_task_history(task_history: TaskHistory) -> None:
    """Decrypt task logs in a TaskHistory record.

    :param task_history:TaskHistory objects to be processed.
    :type task_history:TaskHistory
    :returns: None. The function modifies the task_history in place.
    """
    req = getattr(task_history, "execution_request", None)
    if not req or not isinstance(req.tracking, dict):
        return

    logs = req.tracking.get("task_logs")
    if not isinstance(logs, dict):
        return

    stage_map = {
        "prepare-env": task_history.anonymized_items.prepare_env,
        "run-script": task_history.anonymized_items.run_script,
        "clean-up": task_history.anonymized_items.clean_up,
        "step1": task_history.anonymized_items.step,
    }
    for stage, log in logs.items():
        if not isinstance(log, dict):
            continue
        anonymized = stage_map.get(stage)
        if not anonymized:
            continue
        if log.get("stdout") is not None:
            log["stdout"] = presidio_decrypt_log(log["stdout"], anonymized.stdout)
        if log.get("stderr") is not None:
            log["stderr"] = presidio_decrypt_log(log["stderr"], anonymized.stderr)
