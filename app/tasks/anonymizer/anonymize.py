# Copyright (C) 2025 Percona LLC
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

"""Define the main anonymizing functions."""

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine, OperatorConfig

from app.tasks.anonymizer.entities import PIIEntity

__all__ = ["anonymize_text"]

ANONYMIZER_OPERATORS = {
    "DEFAULT": OperatorConfig("replace", {}),
}
analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()


def anonymize_text(text: str, selected_entities: set[PIIEntity]) -> str:
    """Anonymize text using Microsoft Presidio.

    :param text: The original log text.
    :type text: str
    :param selected_entities: A set of selected anonymizer entities to apply.
    :type selected_entities: set[PIIEntity]
    :return: The encrypted log text.
    :rtype: str
    """
    if selected_entities:
        results = analyzer.analyze(
            text=text,
            entities=[entity.name for entity in selected_entities],
            language="en",
        )
        if results:
            anonymized_result = anonymizer.anonymize(
                text, results, ANONYMIZER_OPERATORS
            )
            return anonymized_result.text
    return text
