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

"""Tests for SnippetMetaParameter model validators and computed properties."""

import pytest
from pydantic import ValidationError

from app.sep.snippets.forms import (
    CheckboxInputElement,
    NumberInputElement,
    SelectElement,
    TextareaElement,
    TextInputElement,
    TextInputHTMLElement,
)
from app.sep.snippets.models.meta import (
    SnippetMetaParameter,
    SnippetMetaParameterType,
)

FLOAT_DEFAULT_STEP = 0.1
INT_DEFAULT_STEP = 1.0
CUSTOM_STEP = 5.0
EXPECTED_INT_DEFAULT = 5
EXPECTED_INT_LT = 100
MIN_LENGTH_TWO = 2
MAX_LENGTH_FIFTY = 50
EXPECTED_PARAM_COUNT = 2
EXPECTED_CONSTRAINT_COUNT = 2
MD5_DIGEST_LENGTH = 32


class TestSetDefaultStep:
    """Test the set_default_step model validator."""

    def test_int_type_gets_step_one(self):
        """Verify INT type sets step to 1.0 when not explicitly provided."""
        param = SnippetMetaParameter(name="count", type=SnippetMetaParameterType.INT)
        assert param.step == 1.0

    def test_float_type_gets_step_point_one(self):
        """Verify FLOAT type sets step to 0.1 when not explicitly provided."""
        param = SnippetMetaParameter(name="ratio", type=SnippetMetaParameterType.FLOAT)
        assert param.step == FLOAT_DEFAULT_STEP

    def test_explicit_step_is_preserved(self):
        """Verify explicitly provided step value is not overridden."""
        param = SnippetMetaParameter(
            name="count", type=SnippetMetaParameterType.INT, step=CUSTOM_STEP
        )
        assert param.step == CUSTOM_STEP

    def test_str_type_has_no_step(self):
        """Verify STR type does not get a default step value."""
        param = SnippetMetaParameter(name="label", type=SnippetMetaParameterType.STR)
        assert param.step is None

    def test_bool_type_has_no_step(self):
        """Verify BOOL type does not get a default step value."""
        param = SnippetMetaParameter(name="flag", type=SnippetMetaParameterType.BOOL)
        assert param.step is None


class TestValidateArgFormat:
    """Test the validate_arg_format model validator."""

    def test_missing_value_placeholder_raises(self):
        """Verify arg_format without ${value} raises ValueError for non-flag params."""
        with pytest.raises(ValidationError, match="arg_format must include"):
            SnippetMetaParameter(
                name="host",
                type=SnippetMetaParameterType.STR,
                arg_format="--host",
            )

    def test_flag_type_allows_arg_format_without_value(self):
        """Verify BOOL type allows arg_format without ${value} placeholder."""
        param = SnippetMetaParameter(
            name="verbose",
            type=SnippetMetaParameterType.BOOL,
            arg_format="--verbose",
        )
        assert param.arg_format == "--verbose"

    def test_valid_arg_format_with_value_placeholder(self):
        """Verify arg_format with ${value} is accepted for non-flag params."""
        param = SnippetMetaParameter(
            name="host",
            type=SnippetMetaParameterType.STR,
            arg_format="--host=${value}",
        )
        assert param.arg_format == "--host=${value}"

    def test_none_arg_format_is_accepted(self):
        """Verify None arg_format passes validation."""
        param = SnippetMetaParameter(name="host", type=SnippetMetaParameterType.STR)
        assert param.arg_format is None


class TestNormalizeChoices:
    """Test the normalize_choices field validator."""

    def test_string_choices_converted_to_dicts(self):
        """Verify string choices are normalized to dicts with 'value' key."""
        param = SnippetMetaParameter(name="color", choices=["red", "green", "blue"])
        assert param.choices == [
            {"value": "red"},
            {"value": "green"},
            {"value": "blue"},
        ]

    def test_dict_choices_preserved(self):
        """Verify dict choices are passed through unchanged."""
        choices = [{"value": "a", "label": "Option A"}, {"value": "b"}]
        param = SnippetMetaParameter(name="opt", choices=choices)
        assert param.choices == choices

    def test_mixed_choices_normalized(self):
        """Verify mixed string and dict choices are handled correctly."""
        param = SnippetMetaParameter(
            name="opt", choices=["x", {"value": "y", "label": "Y Label"}]
        )
        assert param.choices == [
            {"value": "x"},
            {"value": "y", "label": "Y Label"},
        ]


class TestSetDefaultTypeIfUnknown:
    """Test the set_default_type_if_unknown field validator."""

    def test_unknown_type_defaults_to_str(self):
        """Verify unknown type value falls back to STR."""
        param = SnippetMetaParameter(name="field", type="unknown_type")
        assert param.py_type == SnippetMetaParameterType.STR

    def test_valid_type_preserved(self):
        """Verify valid type values are preserved."""
        param = SnippetMetaParameter(name="field", type=SnippetMetaParameterType.INT)
        assert param.py_type == SnippetMetaParameterType.INT


class TestCoerceToType:
    """Test the coerce_to_type field validator."""

    def test_string_default_coerced_to_int(self):
        """Verify string default '5' is coerced to int 5 for INT type."""
        param = SnippetMetaParameter(
            name="count", type=SnippetMetaParameterType.INT, default="5"
        )
        assert param.default == EXPECTED_INT_DEFAULT
        assert isinstance(param.default, int)

    def test_string_default_coerced_to_float(self):
        """Verify string default '3.14' is coerced to float for FLOAT type."""
        param = SnippetMetaParameter(
            name="ratio", type=SnippetMetaParameterType.FLOAT, default="3.14"
        )
        assert param.default == pytest.approx(3.14)

    def test_none_default_preserved(self):
        """Verify None default is not coerced."""
        param = SnippetMetaParameter(
            name="count", type=SnippetMetaParameterType.INT, default=None
        )
        assert param.default is None

    def test_gt_lt_coerced(self):
        """Verify gt and lt values are coerced to the declared type."""
        param = SnippetMetaParameter(
            name="val",
            type=SnippetMetaParameterType.INT,
            gt="0",
            lt="100",
        )
        assert param.gt == 0
        assert isinstance(param.gt, int)
        assert param.lt == EXPECTED_INT_LT
        assert isinstance(param.lt, int)


class TestIsFlag:
    """Test the is_flag computed field."""

    def test_bool_type_is_flag(self):
        """Verify BOOL type returns is_flag=True."""
        param = SnippetMetaParameter(name="flag", type=SnippetMetaParameterType.BOOL)
        assert param.is_flag is True

    def test_str_type_is_not_flag(self):
        """Verify STR type returns is_flag=False."""
        param = SnippetMetaParameter(name="name", type=SnippetMetaParameterType.STR)
        assert param.is_flag is False

    def test_int_type_is_not_flag(self):
        """Verify INT type returns is_flag=False."""
        param = SnippetMetaParameter(name="count", type=SnippetMetaParameterType.INT)
        assert param.is_flag is False


class TestFormFieldElementCls:
    """Test the form_field_element_cls cached property."""

    def test_with_choices_returns_select(self):
        """Verify parameter with choices returns SelectElement."""
        param = SnippetMetaParameter(name="opt", choices=["a", "b"])
        assert param.form_field_element_cls is SelectElement

    def test_bool_type_returns_checkbox(self):
        """Verify BOOL type returns CheckboxInputElement."""
        param = SnippetMetaParameter(name="flag", type=SnippetMetaParameterType.BOOL)
        assert param.form_field_element_cls is CheckboxInputElement

    def test_int_type_returns_number(self):
        """Verify INT type returns NumberInputElement."""
        param = SnippetMetaParameter(name="count", type=SnippetMetaParameterType.INT)
        assert param.form_field_element_cls is NumberInputElement

    def test_float_type_returns_number(self):
        """Verify FLOAT type returns NumberInputElement."""
        param = SnippetMetaParameter(name="ratio", type=SnippetMetaParameterType.FLOAT)
        assert param.form_field_element_cls is NumberInputElement

    def test_str_type_returns_text_input(self):
        """Verify STR type returns TextInputElement by default."""
        param = SnippetMetaParameter(name="name", type=SnippetMetaParameterType.STR)
        assert param.form_field_element_cls is TextInputElement

    def test_textarea_html_elem_returns_textarea(self):
        """Verify STR type with TEXTAREA html_elem returns TextareaElement."""
        param = SnippetMetaParameter(
            name="body",
            type=SnippetMetaParameterType.STR,
            html_elem=TextInputHTMLElement.TEXTAREA,
        )
        assert param.form_field_element_cls is TextareaElement


class TestConstraints:
    """Test the constraints cached property."""

    def test_str_type_with_lengths(self):
        """Verify STR type returns StringConstraints with min/max_length."""
        param = SnippetMetaParameter(
            name="label",
            type=SnippetMetaParameterType.STR,
            min_length=2,
            max_length=50,
        )
        constraints = param.constraints
        assert len(constraints) == 1
        assert constraints[0].min_length == MIN_LENGTH_TWO
        assert constraints[0].max_length == MAX_LENGTH_FIFTY

    def test_int_type_with_gt_lt(self):
        """Verify INT type with gt/lt returns Interval constraint."""
        param = SnippetMetaParameter(
            name="count",
            type=SnippetMetaParameterType.INT,
            gt=0,
            lt=100,
        )
        constraints = param.constraints
        assert len(constraints) == 1
        assert constraints[0].gt == 0
        assert constraints[0].lt == EXPECTED_INT_LT

    def test_str_with_interval_returns_both(self):
        """Verify STR type with ge returns both StringConstraints and Interval."""
        param = SnippetMetaParameter(
            name="code",
            type=SnippetMetaParameterType.STR,
            min_length=1,
            ge="0",
        )
        assert len(param.constraints) == EXPECTED_CONSTRAINT_COUNT

    def test_no_interval_when_no_bounds(self):
        """Verify no Interval constraint when no gt/lt/ge/le specified."""
        param = SnippetMetaParameter(name="name", type=SnippetMetaParameterType.STR)
        assert len(param.constraints) == 1


class TestValidationType:
    """Test the validation_type cached property."""

    def test_with_choices_returns_str_enum(self):
        """Verify required parameter with choices returns a StrEnum type."""
        param = SnippetMetaParameter(name="opt", choices=["a", "b", "c"], required=True)
        vtype = param.validation_type
        assert hasattr(vtype, "__members__")
        assert set(vtype.__members__) == {"a", "b", "c"}

    def test_required_str_returns_raw_type(self):
        """Verify required STR param returns annotated str type."""
        param = SnippetMetaParameter(
            name="host", type=SnippetMetaParameterType.STR, required=True
        )
        assert param.validation_type is not None

    def test_optional_returns_union_with_empty_str_to_none(self):
        """Verify optional param with no default returns union with EmptyStrToNone."""
        param = SnippetMetaParameter(
            name="host", type=SnippetMetaParameterType.STR, required=False
        )
        vtype = param.validation_type
        assert hasattr(vtype, "__args__")


class TestToValidationField:
    """Test the to_validation_field method."""

    def test_returns_field_info(self):
        """Verify to_validation_field returns a FieldInfo instance."""
        param = SnippetMetaParameter(
            name="host",
            type=SnippetMetaParameterType.STR,
            description="Target host",
            default="localhost",
        )
        field = param.to_validation_field()
        assert field.default == "localhost"
        assert field.description == "Target host"
        assert field.alias == "host"

    def test_optional_without_default_sets_none(self):
        """Verify optional param without default gets default=None."""
        param = SnippetMetaParameter(
            name="host", type=SnippetMetaParameterType.STR, required=False
        )
        field = param.to_validation_field()
        assert field.default is None


class TestToFormField:
    """Test the to_form_field method."""

    def test_returns_correct_form_element(self):
        """Verify to_form_field returns an instance of the correct element class."""
        param = SnippetMetaParameter(
            name="count",
            type=SnippetMetaParameterType.INT,
            label="Count",
        )
        form_field = param.to_form_field()
        assert isinstance(form_field, NumberInputElement)

    def test_select_element_for_choices(self):
        """Verify to_form_field returns SelectElement when choices are present."""
        param = SnippetMetaParameter(name="opt", choices=["a", "b"])
        form_field = param.to_form_field()
        assert isinstance(form_field, SelectElement)


class TestConvertValidationErrors:
    """Test the convert_validation_errors static method."""

    def test_converts_to_error_strings(self):
        """Verify ValidationError is converted to a list of readable error strings."""
        try:
            SnippetMetaParameter(name="")
        except ValidationError as exc:
            errors = SnippetMetaParameter.convert_validation_errors(exc, {"name": ""})
            assert len(errors) > 0
            assert all(isinstance(e, str) for e in errors)
            assert any("Parameter error" in e for e in errors)

    def test_dict_input_shows_name(self):
        """Verify dict input with 'name' key shows parameter name in error."""
        try:
            SnippetMetaParameter(name="")
        except ValidationError as exc:
            errors = SnippetMetaParameter.convert_validation_errors(
                exc, {"name": "my_param"}
            )
            assert any("my_param" in e for e in errors)

    def test_non_dict_input_shows_repr(self):
        """Verify non-dict input shows repr in error message."""
        try:
            SnippetMetaParameter(name="")
        except ValidationError as exc:
            errors = SnippetMetaParameter.convert_validation_errors(exc, "bad_input")
            assert any("bad_input" in e for e in errors)
