# Copyright (C) 2026 Percona LLC
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

from unittest.mock import Mock, patch, PropertyMock

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


class TestPresidioEngineManagerInit:
    """Test PresidioEngineManager lazy initialization."""

    @patch("presidio_analyzer.nlp_engine.NlpEngineProvider")
    def test_nlp_engine_lazy_init(self, mock_provider_cls):
        """Assert first nlp_engine access creates the engine and second returns cached."""
        mock_engine = Mock()
        mock_provider_cls.return_value.create_engine.return_value = mock_engine

        manager = PresidioEngineManager()

        first = manager.nlp_engine
        second = manager.nlp_engine

        assert first is mock_engine
        assert second is first
        mock_provider_cls.assert_called_once()
        mock_provider_cls.return_value.create_engine.assert_called_once()

    @patch("presidio_analyzer.AnalyzerEngine")
    @patch("presidio_analyzer.nlp_engine.NlpEngineProvider")
    def test_analyzer_lazy_init(self, mock_provider_cls, mock_analyzer_cls):
        """Assert first analyzer access creates the engine and second returns cached."""
        mock_nlp = Mock()
        mock_provider_cls.return_value.create_engine.return_value = mock_nlp
        mock_analyzer_engine = Mock()
        mock_analyzer_cls.return_value = mock_analyzer_engine

        manager = PresidioEngineManager()

        first = manager.analyzer
        second = manager.analyzer

        assert first is mock_analyzer_engine
        assert second is first
        mock_analyzer_cls.assert_called_once()
        assert mock_analyzer_cls.call_args.kwargs["nlp_engine"] is mock_nlp

    @patch("presidio_anonymizer.AnonymizerEngine")
    def test_anonymizer_lazy_init(self, mock_anonymizer_cls):
        """Assert first anonymizer access creates the engine and second returns cached."""
        mock_anon_engine = Mock()
        mock_anonymizer_cls.return_value = mock_anon_engine

        manager = PresidioEngineManager()

        first = manager.anonymizer
        second = manager.anonymizer

        assert first is mock_anon_engine
        assert second is first
        mock_anonymizer_cls.assert_called_once()

    def test_build_nlp_config(self):
        """Assert _build_nlp_config returns the expected spacy configuration dict."""
        config = PresidioEngineManager._build_nlp_config()

        assert config["nlp_engine_name"] == "spacy"
        assert isinstance(config["models"], list)
        assert len(config["models"]) >= 1
        assert config["models"][0]["lang_code"] == "en"
        assert "model_name" in config["models"][0]


class TestAnonymizeText:
    """Test anonymize_text function."""

    def test_with_multiple_entities(self, mock_analyzer, mock_anonymizer):
        """Assert text is anonymized when multiple entity types are detected."""
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

    def test_with_no_entities(self, mock_analyzer, mock_anonymizer):
        """Assert original text is returned when no entity types are selected."""
        text = "Log without PII"
        result = anonymize_text(text, set())

        assert result == "Log without PII"
        mock_analyzer.analyze.assert_not_called()
        mock_anonymizer.anonymize.assert_not_called()

    def test_no_entities_found(self, mock_analyzer, mock_anonymizer):
        """Assert original text is returned when analyzer finds no entities."""
        mock_analyzer.analyze.return_value = []
        text = "Log with no PII"
        result = anonymize_text(text, {PIIEntity.CREDIT_CARD})

        assert result == "Log with no PII"
        mock_analyzer.analyze.assert_called_once()
        mock_anonymizer.anonymize.assert_not_called()

    def test_with_explicit_language(self, mock_analyzer, mock_anonymizer):
        """Assert explicit language parameter is passed to analyzer.analyze."""
        mock_analyzer.analyze.return_value = []

        anonymize_text(
            text="some text", selected_entities={PIIEntity.PERSON}, language="de"
        )

        mock_analyzer.analyze.assert_called_once()
        assert mock_analyzer.analyze.call_args.kwargs["language"] == "de"

    def test_default_language(self, mock_analyzer, mock_anonymizer):
        """Assert default language from settings is used when language is None."""
        mock_analyzer.analyze.return_value = []

        anonymize_text(text="some text", selected_entities={PIIEntity.PERSON})

        mock_analyzer.analyze.assert_called_once()
        assert mock_analyzer.analyze.call_args.kwargs["language"] == "en"
