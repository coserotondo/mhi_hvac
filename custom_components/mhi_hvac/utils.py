"""Utility functions for the MHI HVAC integration."""

from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed

from .pymhihvac.utils import format_exception


def raise_update_failed(message: str, e: Exception | None = None) -> None:
    """Raise an UpdateFailed exception with the given message, optionally chaining an original exception."""
    if e is not None:
        raise UpdateFailed(f"{message} {format_exception(e)}") from e
    raise UpdateFailed(message)


def raise_config_entry_not_ready(message: str, e: Exception | None = None) -> None:
    """Raise an ConfigEntryNotReady exception with the given message, optionally chaining an original exception."""
    if e is not None:
        raise ConfigEntryNotReady(f"{message} {format_exception(e)}") from e
    raise ConfigEntryNotReady(message)
