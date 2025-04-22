"""Define tests for the app.core.utils.dict module."""

import pytest

from app.core.utils import sort_dict
from app.core.utils.dict import filter_dict, remove_falsy_values_from_dict


def test_sort_dict():
    """Test sort_dict utility for sorting dictionaries."""
    unsorted_dict = {"banana": 3, "apple": 4, "cherry": 2}
    sorted_by_key = sort_dict(unsorted_dict, key=lambda item: item[0])
    assert list(sorted_by_key.keys()) == ["apple", "banana", "cherry"]

    sorted_by_value = sort_dict(unsorted_dict, key=lambda item: item[1])
    assert list(sorted_by_value.keys()) == ["cherry", "banana", "apple"]

    assert sort_dict({}, key=lambda item: item[0]) == {}

    unsorted_dict = {3: "three", 1: "one", 2: "two"}
    sorted_dict = sort_dict(unsorted_dict, key=lambda item: item[0])
    assert list(sorted_dict.keys()) == [1, 2, 3]


@pytest.mark.parametrize(
    ("initial_dict", "filter_func", "expected_result"),
    [
        ({"a": 1, "b": 2, "c": 3, "d": 4}, lambda v: v % 2 == 0, {"b": 2, "d": 4}),
        ({"a": 1, "b": 2, "c": 3}, lambda _: True, {"a": 1, "b": 2, "c": 3}),
        ({"a": 1, "b": 2, "c": 3}, lambda _: False, {}),
        ({}, lambda _: True, {}),
    ],
)
def test_filter_dict(initial_dict, filter_func, expected_result):
    """Test filter_dict function."""
    assert filter_dict(initial_dict, filter_func) == expected_result


@pytest.mark.parametrize(
    ("initial_dict", "expected_result"),
    [
        ({"a": 0, "b": 1, "c": 2, "d": "", "e": []}, {"b": 1, "c": 2}),
        ({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 2, "c": 3}),
        ({"a": 0, "b": None, "c": False}, {}),
        ({}, {}),
    ],
)
def test_remove_falsy_values_from_dict(initial_dict, expected_result):
    """Test remove_falsy_values_from_dict to ensure all falsy values are removed."""
    assert remove_falsy_values_from_dict(initial_dict) == expected_result
