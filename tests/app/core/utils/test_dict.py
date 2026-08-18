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

"""Define tests for the app.core.utils.dict module."""

import pytest

from app.core.utils import sort_dict
from app.core.utils.dict import (
    deep_dict_update,
    filter_dict,
    remove_falsy_values_from_dict,
)


@pytest.mark.parametrize(
    ("main_dict", "update_dict", "expected"),
    [
        (
            {"items": ["a", "b"]},
            {"items": ["c"]},
            {"items": ["c", "a", "b"]},
        ),
        (
            {"items": ["a", "b"]},
            {"items": []},
            {"items": []},
        ),
        (
            {"nested": {"items": [1, 2]}},
            {"nested": {"items": []}},
            {"nested": {"items": []}},
        ),
        (
            {"k": "old"},
            {"k": "new"},
            {"k": "new"},
        ),
    ],
    ids=[
        "prepend-nonempty-list",
        "empty-list-clears",
        "nested-empty-list-clears",
        "scalar-overwrite",
    ],

)
def test_deep_dict_update(main_dict, update_dict, expected):
    """Assert list overlays prepend when non-empty and clear when empty."""
    deep_dict_update(main_dict, update_dict)
    assert main_dict == expected


def test_deep_dict_update_self_merge_is_noop():
    """Assert merging a dict into itself does not double any list."""
    d = {"items": ["a", "b"], "nested": {"nums": [1, 2], "k": "v"}, "s": "x"}
    expected = {"items": ["a", "b"], "nested": {"nums": [1, 2], "k": "v"}, "s": "x"}
    deep_dict_update(d, d)
    assert d == expected


@pytest.mark.parametrize(
    ("unsorted_dict", "key", "expected_keys"),
    [
        (
            {"banana": 3, "apple": 4, "cherry": 2},
            lambda item: item[0],
            ["apple", "banana", "cherry"],
        ),
        (
            {"banana": 3, "apple": 4, "cherry": 2},
            lambda item: item[1],
            ["cherry", "banana", "apple"],
        ),
        ({3: "three", 1: "one", 2: "two"}, lambda item: item[0], [1, 2, 3]),
    ],
    ids=["by-key-string", "by-value", "by-key-int"],
)
def test_sort_dict(unsorted_dict, key, expected_keys):
    """Test sort_dict utility for sorting dictionaries."""
    assert list(sort_dict(unsorted_dict, key=key).keys()) == expected_keys


def test_sort_dict_empty():
    """Test sort_dict returns an empty dict for empty input."""
    assert sort_dict({}, key=lambda item: item[0]) == {}


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
