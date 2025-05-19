"""Define exceptions for the Nomad executor."""

from nomad.api.exceptions import BaseNomadException


class AllocationNotFoundException(BaseNomadException):
    """Define exception for when an allocation is not found."""


class JobNotFoundException(BaseNomadException):
    """Define exception for when a job is not found."""
