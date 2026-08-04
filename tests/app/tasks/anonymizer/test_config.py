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

"""Define tests for the app.tasks.anonymizer.config module."""

from collections import defaultdict
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import YamlPrefixConfigSettingsSource
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.tasks.anonymizer.config import anonymizer_settings, AnonymizerSettings
from app.tasks.anonymizer.entities import PIIEntity

HIGH_CONFIDENCE_DEFAULT_ENTITIES = {
    PIIEntity.CREDIT_CARD,
    PIIEntity.EMAIL_ADDRESS,
    PIIEntity.IBAN_CODE,
    PIIEntity.IP_ADDRESS,
    PIIEntity.PHONE_NUMBER,
    PIIEntity.US_SSN,
    PIIEntity.US_ITIN,
}

PII_ENTITY_MEMBER_COUNT = 14


def _entities_for_profile(profile: str) -> set[PIIEntity]:
    """Load ``DEFAULT_ENTITIES`` for a settings.yaml profile via the production merge."""
    source = YamlPrefixConfigSettingsSource(
        AnonymizerSettings,
        prefixes=(profile, *AnonymizerSettings.SETTINGS_PREFIXES),
    )
    settings = AnonymizerSettings(DEFAULT_ENTITIES=source.yaml_data["DEFAULT_ENTITIES"])
    return settings.DEFAULT_ENTITIES["any_owner"]


class TestSettingsYamlAnonymizerProfiles:
    """Assert shipped settings.yaml profiles resolve the expected entity sets."""

    @pytest.mark.parametrize(
        ("profile", "expected"),
        [
            ("default", HIGH_CONFIDENCE_DEFAULT_ENTITIES),
            ("development", set()),
        ],
        ids=["default-high-confidence", "development-empty"],
    )
    def test_profile_resolves_expected_entities(
        self, profile: str, expected: set[PIIEntity]
    ) -> None:
        """Assert each profile resolves to the expected ``DEFAULT_ENTITIES`` set."""
        assert _entities_for_profile(profile) == expected

    def test_pii_entity_retains_all_fourteen_members(self) -> None:
        """Assert narrowing is configuration-only; ``PIIEntity`` still has 14 members."""
        assert len(PIIEntity) == PII_ENTITY_MEMBER_COUNT


class TestValidateEntitiesDefaultdict:
    """Test the _validate_entities_defaultdict validator."""

    def test_star_creates_defaultdict_with_all_entities(self):
        """Assert '*' produces a defaultdict returning all PIIEntity values."""
        settings = AnonymizerSettings(DEFAULT_ENTITIES="*")
        result = settings.DEFAULT_ENTITIES["any_owner"]
        assert result == set(PIIEntity)

    def test_list_of_entity_names_creates_defaultdict(self):
        """Assert a list of entity names creates a defaultdict with those entities."""
        entities = ["CREDIT_CARD", "EMAIL_ADDRESS"]
        settings = AnonymizerSettings(DEFAULT_ENTITIES=entities)
        result = settings.DEFAULT_ENTITIES["any_owner"]
        assert result == {PIIEntity.CREDIT_CARD, PIIEntity.EMAIL_ADDRESS}

    def test_dict_creates_defaultdict_with_empty_set_default(self):
        """Assert a dict input creates a defaultdict with empty set as default."""
        input_dict = {"owner_a": {PIIEntity.PERSON}}
        settings = AnonymizerSettings(DEFAULT_ENTITIES=input_dict)
        assert settings.DEFAULT_ENTITIES["owner_a"] == {PIIEntity.PERSON}
        assert settings.DEFAULT_ENTITIES["unknown_owner"] == set()

    def test_empty_dict_creates_defaultdict_with_empty_sets(self):
        """Assert an empty dict creates a defaultdict returning empty sets."""
        settings = AnonymizerSettings(DEFAULT_ENTITIES={})
        assert isinstance(settings.DEFAULT_ENTITIES, defaultdict)
        assert settings.DEFAULT_ENTITIES["any_key"] == set()


class TestAnonymizerSettingsProperties:
    """Test AnonymizerSettings properties and methods."""

    def test_settings_prefixes(self):
        """Assert SETTINGS_PREFIXES is ['TASKS', 'ANONYMIZER']."""
        assert AnonymizerSettings.SETTINGS_PREFIXES == ["TASKS", "ANONYMIZER"]

    def test_default_nlp_models(self):
        """Assert default NLP_MODELS contains English model."""
        assert anonymizer_settings.NLP_MODELS == {"en": "en_core_web_sm"}

    def test_default_analyzer_language(self):
        """Assert default_analyzer_language returns first key from NLP_MODELS."""
        assert anonymizer_settings.default_analyzer_language == "en"

    def test_default_analyzer_language_custom_models(self):
        """Assert default_analyzer_language returns first key from custom models."""
        settings = AnonymizerSettings(
            NLP_MODELS={"de": "de_core_news_sm", "en": "en_core_web_sm"}
        )
        assert settings.default_analyzer_language == "de"

    def test_get_anonymize_mask_empty_entities(self):
        """Assert get_anonymize_mask returns 0 for owner with no entities."""
        settings = AnonymizerSettings(DEFAULT_ENTITIES={})
        assert settings.get_anonymize_mask("unknown_owner") == 0

    def test_get_anonymize_mask_with_entities(self):
        """Assert get_anonymize_mask returns correct bitmask for configured entities."""
        settings = AnonymizerSettings(
            DEFAULT_ENTITIES={
                "test_owner": {PIIEntity.CREDIT_CARD, PIIEntity.EMAIL_ADDRESS}
            }
        )
        expected = PIIEntity.CREDIT_CARD | PIIEntity.EMAIL_ADDRESS
        assert settings.get_anonymize_mask("test_owner") == expected

    def test_get_anonymize_mask_star_entities(self):
        """Assert get_anonymize_mask with '*' returns mask for all entities."""
        settings = AnonymizerSettings(DEFAULT_ENTITIES="*")
        mask = settings.get_anonymize_mask("any_owner")
        assert mask == PIIEntity.encode_selection(set(PIIEntity))

    def test_singleton_is_overridable_proxy_that_resolves_reads(self):
        """Assert the singleton is an override-aware proxy that resolves reads."""
        assert isinstance(anonymizer_settings, OverridableSettingsProxy)
        assert anonymizer_settings.NLP_MODELS == {"en": "en_core_web_sm"}

    @pytest.mark.parametrize(
        "nlp_models",
        [
            {"en": "en_core_web_sm"},
            {"fr": "fr_core_news_sm", "en": "en_core_web_sm"},
        ],
    )
    def test_nlp_models_validation(self, nlp_models):
        """Assert NLP_MODELS accepts valid non-empty dicts."""
        settings = AnonymizerSettings(NLP_MODELS=nlp_models)
        assert nlp_models == settings.NLP_MODELS

    def test_nlp_models_rejects_empty_dict(self):
        """Assert NLP_MODELS rejects an empty dict due to min_length=1."""
        with pytest.raises(ValidationError, match="at least 1 item"):
            AnonymizerSettings(NLP_MODELS={})
