"""Define a logging filter to mask secrets and hash PII using Presidio."""

import json
import logging

from presidio_analyzer import AnalyzerEngine, PatternRecognizer
from presidio_anonymizer import (
    AnonymizerEngine,
    ConflictResolutionStrategy,
    OperatorConfig,
)

SECRET_FIELDS = {
    "client_secret": "<CLIENT_SECRET>",
    "access_token": "<TOKEN>",
    "accessToken": "<TOKEN>",
    "refresh_token": "<TOKEN>",
    "refreshToken": "<TOKEN>",
    "id_token": "<TOKEN>",
    "token": "<TOKEN>",
    "client_id": "<TOKEN>",
    "sub": "<TOKEN>",
    "password": "***",
}

# Define fields considered as PII that should be hashed.
PII_FIELDS = {"email", "phone"}

# Keys to exclude from JSON serialization.
EXCLUDE_KEYS = {"ssl"}

# List of classes (or module fragments) to exclude from filtering.
INCLUDE_CLASSES = {"app.core.auth.providers.casdoor"}


class PresidioRemoteAPIFilter(logging.Filter):
    """A logging filter that uses Microsoft Presidio to detect and anonymize sensitive data.

    This filter processes log record arguments to mask known secrets and to apply a custom
    anonymizer (e.g., hashing) for PII fields. It only processes records coming from the target logger.
    """

    def __init__(
        self,
        logger_name: str,
        *,
        console_log_masking: bool,
        hashing_salt: str = "SECRET_KEY",
    ) -> None:
        """Initialize the PresidioRemoteAPIFilter.

        :param logger_name: The name of the logger to filter.
        :type logger_name: str
        :param console_log_masking: Whether to mask logs in the console output.
        :type console_log_masking: bool
        :param hashing_salt: Salt to use for hashing PII values.
        :type hashing_salt: str
        """
        # TODO: Find a way to use settings.SECRET_KEY attribute without circular import  # noqa: TD002, TD003
        super().__init__(logger_name)
        self.logger_name = logger_name
        self.hashing_salt = hashing_salt
        self.console_log_masking = console_log_masking
        self.analyzer = AnalyzerEngine()
        self.anonymizer = AnonymizerEngine()

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter and sanitize log record arguments.

        This method converts dictionary arguments to JSON, analyzes them with Presidio using
        ad-hoc recognizers, and anonymizes sensitive fields based on predefined configurations.

        :param record: The log record to process.
        :type record: logging.LogRecord
        :return: True if the record should be logged, False otherwise.
        :rtype: bool
        """
        if not self.console_log_masking:
            return True

        for include in INCLUDE_CLASSES:
            if include.lower() not in record.name.lower():
                return True

        sanitized_args = []
        for arg in record.args:
            if isinstance(arg, dict):
                sanitized_args.append(self._sanitize_dict_arg(arg))
            elif isinstance(arg, list):
                sanitized_args.append(self._sanitize_list_arg(arg))
            else:
                sanitized_args.append(arg)
        record.args = tuple(sanitized_args)
        return True

    def _sanitize_dict_arg(self, arg: dict) -> str:
        """Sanitize a dictionary argument by converting it to JSON and anonymizing sensitive fields.

        :param arg: The dictionary to sanitize.
        :type arg: dict
        :return: The anonymized JSON string.
        :rtype: str
        """
        arg_for_serialization = {k: v for k, v in arg.items() if k not in EXCLUDE_KEYS}
        text = json.dumps(arg_for_serialization)

        ad_hoc_recognizers = []
        operators_config = {}
        self._create_recognizers_and_operator_config(
            arg_for_serialization, ad_hoc_recognizers, operators_config
        )

        results = self.analyzer.analyze(
            text=text,
            language="en",
            score_threshold=1,
            ad_hoc_recognizers=ad_hoc_recognizers,
        )

        anonymized = self.anonymizer.anonymize(
            text,
            results,
            operators=operators_config,
            conflict_resolution=ConflictResolutionStrategy.REMOVE_INTERSECTIONS,
        )
        return anonymized.text

    def _sanitize_list_arg(self, arg_list: list) -> list:
        """Sanitize a list argument, processing any dictionary elements.

        :param arg_list: The list to sanitize.
        :type arg_list: list
        :return: The sanitized list.
        :rtype: list
        """
        sanitized_list = []
        for item in arg_list:
            if isinstance(item, dict):
                sanitized_list.append(self._sanitize_dict_arg(item))
            elif isinstance(item, list):
                sanitized_list.append(self._sanitize_list_arg(item))
            else:
                sanitized_list.append(item)
        return sanitized_list

    def _create_recognizers_and_operator_config(
        self, data: list, ad_hoc_recognizers: list, operators_config: dict
    ) -> None:
        """Recursively traverse data to create ad-hoc recognizers and operator configurations for sensitive keys.

        :param data: The data structure (dict or list) to traverse.
        :param ad_hoc_recognizers: The list to append recognizers to.
        :param operators_config: The dictionary to populate with operator configurations.
        :return: None
        """
        if isinstance(data, dict):
            for key, value in data.items():
                if key in SECRET_FIELDS or key in PII_FIELDS:
                    recognizer = PatternRecognizer(
                        supported_entity=key.upper(), deny_list=[str(value)]
                    )
                    ad_hoc_recognizers.append(recognizer)
                    entity = key.upper()
                    if key in SECRET_FIELDS:
                        operators_config[entity] = OperatorConfig(
                            "replace", {"new_value": SECRET_FIELDS[key]}
                        )
                    elif key in PII_FIELDS:
                        operators_config[entity] = OperatorConfig(
                            "hash", {"hashing_salt": self.hashing_salt}
                        )
                self._create_recognizers_and_operator_config(
                    value, ad_hoc_recognizers, operators_config
                )
        elif isinstance(data, list):
            for item in data:
                self._create_recognizers_and_operator_config(
                    item, ad_hoc_recognizers, operators_config
                )
