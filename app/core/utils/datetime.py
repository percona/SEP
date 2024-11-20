"""Define datetime utilities."""

from datetime import datetime, UTC


def utc_now() -> datetime:
    """Get current UTC datetime with microsecond set to 0.

    :return: Current aware datetime with timezone set to UTC.
    :rtype: datetime
    """
    return datetime.now(UTC).replace(microsecond=0)


def make_datetime_utc(dt: datetime) -> datetime:
    """Convert a datetime to UTC.

    This method converts an aware datetime to UTC, or just adds UTC tzinfo
    to a naive datetime.

    :param dt: Datetime to convert timezone.
    :type dt: datetime
    :return: Aware datetime with timezone set to UTC.
    :rtype: datetime
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
