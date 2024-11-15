"""Define utilities for handling dictionaries."""

from collections.abc import Callable
from typing import Any

__all__ = [
    "deep_dict_update",
    "transform_dict_keys",
    "sort_dict",
]


def deep_dict_update(main_dict: dict[Any, Any], update_dict: dict[Any, Any]) -> None:
    """Recursively merge `update_dict` into `main_dict`.

    Update `main_dict` with the contents of `update_dict` recursively. For each
    key in `update_dict`, if the key exists in `main_dict` and both values are
    dictionaries, merge them recursively. If the key exists in `main_dict` and
    both values are lists, prepend the list from `update_dict` to the list in
    `main_dict`. Otherwise, overwrite the value in `main_dict` with the value
    from `update_dict`.

    :param main_dict: The dictionary to be updated.
    :type main_dict: dict[Any, Any]
    :param update_dict: The dictionary containing updates to apply.
    :type update_dict: dict[Any, Any]
    """
    for key, value in update_dict.items():
        if (
            key in main_dict
            and isinstance(main_dict[key], dict)
            and isinstance(value, dict)
        ):
            deep_dict_update(main_dict[key], value)
        elif (
            key in main_dict
            and isinstance(main_dict[key], list)
            and isinstance(update_dict[key], list)
        ):
            main_dict[key] = update_dict[key] + main_dict[key]
        else:
            main_dict[key] = value


def transform_dict_keys(
    data: dict[Any, Any], transform: Callable[[Any], Any], *, deep: bool = False
) -> dict[Any, Any]:
    """Transform all keys in a dictionary using a specified function.

    Traverse the input dictionary and transform all keys using the specified `transform`
    function. If a value is a dictionary and `deep` is True, apply the conversion
    recursively.

    :param data: The dictionary whose keys are to be transformed.
    :type data: dict[Any, Any]
    :param transform: The transform function to use.
    :type transform: Callable[[Any], Any]
    :param deep: If `True`, apply the transform function recursively to all sub-dicts.
        Defaults to False.
    :type deep: bool
    :return: A new dictionary with all keys transformed.
    :rtype: dict[Any, Any]
    """
    transformed_dict = {}
    for key, value in data.items():
        new_value = (
            transform_dict_keys(value, transform, deep=deep)
            if deep and isinstance(value, dict)
            else value
        )
        transformed_dict[transform(key)] = new_value
    return transformed_dict


def sort_dict(unsorted_dict: dict, key: Callable[[Any], Any]) -> dict:
    """Sort a dictionary based on a specified key function.

    This function returns a new dictionary with its items sorted according to the
    provided key function. The sorting is performed on the dictionary's items, and the
    resulting dictionary maintains the sorted order.

    :param unsorted_dict: The dictionary to be sorted.
    :type unsorted_dict: dict
    :param key: A function that extracts a comparison key from each dictionary item.
    :type key: Callable[[Any], Any]
    :return: A new dictionary sorted by the specified key function.
    :rtype: dict
    """
    return dict(sorted(unsorted_dict.items(), key=key))
