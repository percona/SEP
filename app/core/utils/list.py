"""Define utilities for handling lists."""

__all__ = ["remove_duplicates"]


def remove_duplicates(v: list) -> list:
    """Remove duplicates from a list while maintaining order.

    :param v: The list to remove duplicates from.
    :type v: list
    :return: The list without duplicates.
    :rtype: list
    """
    unique_list = []
    for item in v:
        if item not in unique_list:
            unique_list.append(item)
    return unique_list
