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

"""Define tests for the app.core.utils.pydantic module."""

import threading
from dataclasses import dataclass
from typing import Annotated

import pytest
from pydantic import BaseModel, StringConstraints, ValidationError
from pydantic.fields import FieldInfo

from app.core.pagination.models import PaginatedDictPage
from app.core.utils.fields import FilenameExtension, MimeType, StrAsyncDatabaseUrl
from app.core.utils.pydantic import (
    _type_adapter,
    blank_str_values_to_none,
    CustomFieldMetadata,
    extract_model_from_instance,
    field_with_metadata,
    loc_to_dot_sep,
    run_pydantic_type_validator,
)
from app.sep.snippets.config import SnippetFilter, SnippetFilterType, SnippetSudoOption
from app.sep.snippets.models.meta import SnippetMetaParameterType
from app.tasks.anonymizer.entities import PIIEntity


@dataclass(eq=True)
class _UnhashableMetadata:
    """Stand in for pydantic metadata a future change forgets to freeze."""

    values: list[int]


class TestCustomFieldMetadata:
    """Test the CustomFieldMetadata NamedTuple and its classmethods."""

    def test_from_dict(self):
        """Return a list of CustomFieldMetadata from a dictionary."""
        data = {"key1": "value1", "key2": 42}
        result = CustomFieldMetadata.from_dict(data)

        expected = [
            CustomFieldMetadata(key="key1", value="value1"),
            CustomFieldMetadata(key="key2", value=42),
        ]
        assert result == expected

    def test_from_dict_empty(self):
        """Return an empty list from an empty dictionary."""
        result = CustomFieldMetadata.from_dict({})
        assert result == []

    def test_from_field_strict(self):
        """Extract only exact CustomFieldMetadata instances in strict mode."""
        meta1 = CustomFieldMetadata(key="color", value="blue")
        meta2 = CustomFieldMetadata(key="size", value=10)
        field = FieldInfo(annotation=str, default=None)
        field.metadata = [meta1, "not_a_metadata", meta2, 42]

        result = CustomFieldMetadata.from_field(field, strict=True)

        assert result == [meta1, meta2]

    def test_from_field_non_strict(self):
        """Coerce compatible metadata items via validation in non-strict mode."""
        meta = CustomFieldMetadata(key="color", value="blue")
        coercible = ("size", 10)
        field = FieldInfo(annotation=str, default=None)
        field.metadata = [meta, coercible, "not_coercible"]

        result = CustomFieldMetadata.from_field(field, strict=False)

        expected = [meta, CustomFieldMetadata(key="size", value=10)]
        assert result == expected

    def test_from_field_non_strict_skips_invalid(self):
        """Skip items that cannot be coerced in non-strict mode."""
        field = FieldInfo(annotation=str, default=None)
        field.metadata = ["not_valid", 123, {"a": "dict"}]

        result = CustomFieldMetadata.from_field(field, strict=False)

        assert result == []

    def test_field_to_dict(self):
        """Convert field metadata to a dictionary via from_field + to_dict chain."""
        meta1 = CustomFieldMetadata(key="color", value="blue")
        meta2 = CustomFieldMetadata(key="size", value=10)
        field = FieldInfo(annotation=str, default=None)
        field.metadata = [meta1, meta2]

        result = CustomFieldMetadata.field_to_dict(field, strict=True)

        assert result == {"color": "blue", "size": 10}

    def test_to_dict(self):
        """Convert a list of CustomFieldMetadata instances to a dictionary."""
        meta1 = CustomFieldMetadata(key="a", value=1)
        meta2 = CustomFieldMetadata(key="b", value="two")

        result = CustomFieldMetadata.to_dict(meta1, meta2)

        assert result == {"a": 1, "b": "two"}

    def test_to_dict_empty(self):
        """Return an empty dictionary when no metadata is provided."""
        result = CustomFieldMetadata.to_dict()
        assert result == {}


class TestFieldWithMetadata:
    """Test the field_with_metadata function."""

    def test_field_with_metadata_creates_field_with_custom_metadata(self):
        """Create a Pydantic Field with custom metadata entries."""
        input_metadata = {"key1": "val1", "key2": "val2"}
        field = field_with_metadata(default="test", metadata=input_metadata)

        assert isinstance(field, FieldInfo)
        assert field.default == "test"

        custom_meta = [m for m in field.metadata if isinstance(m, CustomFieldMetadata)]
        meta_dict = {m.key: m.value for m in custom_meta}
        assert meta_dict == input_metadata

    def test_field_with_metadata_none_metadata(self):
        """Create a Field with no custom metadata when metadata is None."""
        field = field_with_metadata(default="test", metadata=None)

        assert isinstance(field, FieldInfo)
        custom_meta = [m for m in field.metadata if isinstance(m, CustomFieldMetadata)]
        assert custom_meta == []


class TestRunPydanticTypeValidator:
    """Test the run_pydantic_type_validator function."""

    def test_validates_correct_type(self):
        """Return the validated object for a valid input."""
        value = 42
        result = run_pydantic_type_validator(int, value)
        assert result == value

    def test_coerces_compatible_type(self):
        """Coerce a compatible value to the target type."""
        value = 42
        result = run_pydantic_type_validator(float, value)
        assert isinstance(result, float)
        assert result == float(value)

    def test_raises_validation_error_for_invalid_type(self):
        """Raise ValidationError for an incompatible value."""
        with pytest.raises(ValidationError):
            run_pydantic_type_validator(int, "not_an_int")


class TestTypeAdapterCache:
    """Test the memoized TypeAdapter factory behind run_pydantic_type_validator."""

    @pytest.fixture(autouse=True)
    def _isolated_cache(self):
        """Isolate hit/miss assertions from types other tests already warmed."""
        _type_adapter.cache_clear()
        yield
        _type_adapter.cache_clear()

    def test_builds_adapter_once_per_type(self):
        """Build the adapter on the first call and reuse it on the next."""
        run_pydantic_type_validator(int, 1)
        run_pydantic_type_validator(int, 2)

        info = _type_adapter.cache_info()
        assert (info.misses, info.hits) == (1, 1)

    def test_returns_the_same_adapter_instance(self):
        """Return the identical adapter object for repeat calls with one type."""
        assert _type_adapter(int) is _type_adapter(int)

    def test_keeps_adapters_separate_per_type(self):
        """Key the cache per type so no type is validated by another's adapter."""
        integer, boolean = "42", "yes"

        assert run_pydantic_type_validator(int, integer) == int(integer)
        assert run_pydantic_type_validator(bool, boolean) is True

        info = _type_adapter.cache_info()
        assert (info.misses, info.hits) == (2, 0)

    def test_reuses_adapter_for_equal_generic_aliases(self):
        """Hit the cache for a parameterized generic rebuilt as a separate object."""
        first, second = set[int], set[int]
        assert first is not second

        assert _type_adapter(first) is _type_adapter(second)
        assert _type_adapter.cache_info().misses == 1

    def test_reuses_adapter_for_an_annotated_alias(self):
        """Hit the cache for the Annotated alias shape real call sites pass."""
        alias = Annotated[str, StringConstraints(to_lower=True)]

        assert run_pydantic_type_validator(alias, "ABC") == "abc"
        assert run_pydantic_type_validator(alias, "DEF") == "def"
        assert _type_adapter.cache_info().misses == 1

    def test_accepts_unhashable_objects(self):
        """Validate unhashable payloads: only the type is a cache key."""
        assert run_pydantic_type_validator(dict[str, int], {"a": 1}) == {"a": 1}
        assert run_pydantic_type_validator(list[int], ["1", "2"]) == [1, 2]

    def test_returns_independent_results_per_call(self):
        """Return a fresh object per call so a shared adapter carries no state."""

        class Item(BaseModel):
            name: str

        first = run_pydantic_type_validator(Item, {"name": "a"})
        second = run_pydantic_type_validator(Item, {"name": "b"})

        assert first is not second
        assert (first.name, second.name) == ("a", "b")

    def test_cached_adapter_survives_a_validation_error(self):
        """Keep the cached adapter usable after it rejects a value.

        ``CustomFieldMetadata.from_field`` validates every metadata item under
        ``suppress(ValidationError)``, so rejections outnumber successes there.
        """
        with pytest.raises(ValidationError):
            run_pydantic_type_validator(int, "not_an_int")

        value = 7
        assert run_pydantic_type_validator(int, value) == value

        with pytest.raises(ValidationError):
            run_pydantic_type_validator(int, "still_not_an_int")

    def test_converges_on_one_entry_under_concurrent_misses(self):
        """Leave one cache entry when threads miss on the same cold type.

        ``cache`` does not serialize the build, so a cold race may construct
        more than one adapter; every adapter must still validate and only one
        may survive in the cache.
        """

        class Item(BaseModel):
            name: str

        thread_count = 2
        barrier = threading.Barrier(thread_count)
        adapters = []

        def build():
            barrier.wait()
            adapters.append(_type_adapter(Item))

        threads = [threading.Thread(target=build) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(adapters) == thread_count
        assert all(a.validate_python({"name": "a"}).name == "a" for a in adapters)
        assert _type_adapter.cache_info().currsize == 1

    def test_validates_an_unhashable_type_without_caching(self):
        """Validate a type expression that cannot key the cache, uncached."""
        alias = Annotated[int, _UnhashableMetadata([1])]
        first, second = "1", "2"

        assert run_pydantic_type_validator(alias, first) == int(first)
        assert run_pydantic_type_validator(alias, second) == int(second)
        assert _type_adapter.cache_info().currsize == 0


class TestProductionCacheKeys:
    """Test that the known call-site types can key the adapter cache."""

    def test_call_site_types_are_hashable(self):
        """Keep every type listed here usable as a cache key.

        Four are ``Annotated`` aliases that hash only because their pydantic
        metadata is frozen. An unfrozen metadata dataclass added to one of them
        still validates, but silently drops that call site back to rebuilding
        its adapter per call, so the loss shows up here instead. The list is
        maintained by hand, so a new call site must be added to it.
        """
        call_site_types = {
            "PaginatedDictPage": PaginatedDictPage,
            "CustomFieldMetadata": CustomFieldMetadata,
            "StrAsyncDatabaseUrl": StrAsyncDatabaseUrl,
            "FilenameExtension": FilenameExtension,
            "MimeType": MimeType,
            "SnippetFilter": SnippetFilter,
            "SnippetFilterType": SnippetFilterType,
            "SnippetSudoOption": SnippetSudoOption,
            "set[PIIEntity]": set[PIIEntity],
        } | {
            f"SnippetMetaParameterType.{member.name}": member.value
            for member in SnippetMetaParameterType
        }

        unhashable = sorted(
            name for name, key in call_site_types.items() if not _is_hashable(key)
        )
        assert unhashable == []


def _is_hashable(value: object) -> bool:
    """Return whether ``value`` can be used as a dict or cache key."""
    try:
        hash(value)
    except TypeError:
        return False
    return True


class TestExtractModelFromInstance:
    """Test the extract_model_from_instance function."""

    def test_extract_matching_fields(self):
        """Filter fields from a larger model to a smaller target model."""

        class SourceModel(BaseModel):
            name: str
            age: int
            email: str

        class TargetModel(BaseModel):
            name: str
            age: int

        source = SourceModel(name="Alice", age=30, email="alice@example.com")
        result = extract_model_from_instance(source, TargetModel)

        assert isinstance(result, TargetModel)
        assert result.name == source.name
        assert result.age == source.age

    def test_extract_raises_validation_error_for_invalid_data(self):
        """Raise ValidationError when filtered data fails target model validation."""

        class SourceModel(BaseModel):
            name: str
            value: str

        class TargetModel(BaseModel):
            name: str
            value: int

        source = SourceModel(name="test", value="not_a_number")
        with pytest.raises(ValidationError):
            extract_model_from_instance(source, TargetModel)

    def test_extract_ignores_missing_fields(self):
        """Fall back to the target field's default when the source omits it."""

        class SourceModel(BaseModel):
            name: str

        class TargetModel(BaseModel):
            name: str
            age: int = 0

        source = SourceModel(name="Bob")
        result = extract_model_from_instance(source, TargetModel)

        assert result.name == source.name
        assert result.age == 0


class TestLocToDotSep:
    """Test the loc_to_dot_sep function."""

    @pytest.mark.parametrize(
        ("loc", "expected"),
        [
            (("a", "b", "c"), "a.b.c"),
            (("field",), "field"),
            (("items", 0, "value"), "items[0].value"),
            (("data", 1, "nested", 2, "field"), "data[1].nested[2].field"),
            ((0, "field"), "[0].field"),
            ((), ""),
        ],
        ids=[
            "strings_only",
            "single_string",
            "string_int_string",
            "mixed_multiple",
            "leading_int",
            "empty_tuple",
        ],
    )
    def test_loc_to_dot_sep(self, loc, expected):
        """Convert location tuples to dot-separated string paths."""
        assert loc_to_dot_sep(loc) == expected

    def test_loc_to_dot_sep_type_error(self):
        """Raise TypeError for non-str/int elements in the location tuple."""
        with pytest.raises(TypeError, match="Unexpected type"):
            loc_to_dot_sep(("field", 3.14))


class TestBlankStrValuesToNone:
    """Test the blank_str_values_to_none mapping coercion helper."""

    def test_coerces_only_empty_strings(self):
        """Coerce empty-string values to None and leave other values untouched."""
        result = blank_str_values_to_none(
            {"a": "", "b": "x", "c": 0, "d": None, "e": False}
        )
        assert result == {"a": None, "b": "x", "c": 0, "d": None, "e": False}

    def test_passes_through_scalar(self):
        """Return a scalar input unchanged."""
        assert blank_str_values_to_none("scalar") == "scalar"

    def test_passes_through_list(self):
        """Return a list input unchanged, including empty strings inside it."""
        assert blank_str_values_to_none([1, ""]) == [1, ""]
