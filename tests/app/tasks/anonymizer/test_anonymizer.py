# Copyright 2026 Percona LLC
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

"""Define tests for the app.tasks.anonymizer.anonymize module."""

from unittest.mock import Mock, PropertyMock

import pytest

from app.tasks.anonymizer.anonymize import anonymize_text, PresidioEngineManager
from app.tasks.anonymizer.entities import PIIEntity


@pytest.fixture
def mock_analyzer(mocker) -> Mock:
    """Mock the analyzer engine."""
    pm = mocker.patch.object(
        PresidioEngineManager, "analyzer", new_callable=PropertyMock
    )
    analyzer = Mock()
    pm.return_value = analyzer
    return analyzer


@pytest.fixture
def mock_anonymizer(mocker) -> Mock:
    """Mock the anonymizer engine."""
    pm = mocker.patch.object(
        PresidioEngineManager, "anonymizer", new_callable=PropertyMock
    )
    anonymizer = Mock()
    pm.return_value = anonymizer
    return anonymizer


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
