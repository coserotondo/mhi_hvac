"""Utility functions for the MHI HVAC integration."""

from typing import Any

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


def join_if_list(value) -> str | Any:
    """Join list elements with commas if the input is a list.

    This function checks if the input value is a list.
    If it is a list, it joins the elements with commas and returns the resulting string; otherwise, it returns the original value.

    Args:
        value: The input value, which can be a list or any other type.

    Returns:
        str or any: The comma-separated string if the input is a list, or the original value otherwise.

    """

    return ", ".join(value) if isinstance(value, list) else value


def split_if_string(value) -> list[Any] | Any:
    """Split a string by commas if the input is a string.

    This function checks if the input value is a string.
    If it is a string, it splits the string by commas, strips whitespace from each part, and returns a list of non-empty parts; otherwise, it returns the original value.

    Args:
        value: The input value, which can be a string or any other type.

    Returns:
        list or any: A list of strings if the input is a string, or the original value otherwise.

    """

    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value
