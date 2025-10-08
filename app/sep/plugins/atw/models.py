from enum import StrEnum  # noqa: D100


class ParentCategory(StrEnum):
    """Enumerate top-level categories for ATW."""

    CRASHES = "Crashes"
    PERFORMANCE_ISSUES = "Performance Issues"
    REPLICATION_HA = "Replication High / Availability"


class ATWCategory(StrEnum):
    """Enumerate categories for ATW (Advanced Troubleshooting Wizard)."""

    # --- Crashes ---
    SERVER_CRASHED_RESTART_SUCCESSFUL = (
        "Server crashed - Restart Successful",
        ParentCategory.CRASHES,
    )
    SERVER_CRASHED_RESTART_NOT_SUCCESSFUL = (
        "Server crashed - Restart not Successful",
        ParentCategory.CRASHES,
    )

    # --- Performance Issues ---
    OVERALL_SLOWNESS = ("Overall Slowness", ParentCategory.PERFORMANCE_ISSUES)
    QUERY_TUNING_OPTIMIZATION = (
        "Query Tuning / Optimization",
        ParentCategory.PERFORMANCE_ISSUES,
    )
    NOT_RESPONDING = ("Not Responding", ParentCategory.PERFORMANCE_ISSUES)
    WRITES_ARE_BLOCKED = ("Writes are Blocked", ParentCategory.PERFORMANCE_ISSUES)
    PERFORMANCE_OTHER = ("Other", ParentCategory.PERFORMANCE_ISSUES)
    TEMPORARY_STALLS = ("Temporary Stalls", ParentCategory.PERFORMANCE_ISSUES)

    # --- Replication High / Availability ---
    NATIVE_ASYNC_REPLICATION = (
        "Native Asynchronous Replication",
        ParentCategory.REPLICATION_HA,
    )
    MULTI_SOURCE_REPLICATION = (
        "Multi-Source replication",
        ParentCategory.REPLICATION_HA,
    )
    GALERA = ("Galera", ParentCategory.REPLICATION_HA)
    GROUP_REPLICATION = ("Group Replication", ParentCategory.REPLICATION_HA)

    def __new__(cls, label: str, parent: ParentCategory) -> "ATWCategory":  # noqa: D102
        obj = str.__new__(cls, label)
        obj._value_ = label
        obj._parent = parent  # noqa: SLF001
        return obj

    @property
    def parent(self) -> ParentCategory:
        """Return the parent category of the current category."""
        return self._parent
