"""Helper functions for the MHI HVAC integration config flow."""

import json
import re
from typing import Literal

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, ENTITY_SUFFIXES, MAX_GROUP_NO, MIN_GROUP_NO


class GroupCfgInvalidException(Exception):
    """Raised when the group configuration is invalid (no valid groups)."""


class GroupCfgWarning(Exception):
    """Raised when some groups were invalid but some valid groups remain.

    This exception carries the sanitized groups along with a message.
    """

    def __init__(self, sanitized_groups: dict, message: str) -> None:
        """Initialize the exception with sanitized groups and a message.

        Args:
            sanitized_groups (dict): The remaining valid groups.
            message (str): The warning message.

        """
        self.sanitized_groups = sanitized_groups
        self.message = message
        super().__init__(message)


def clamp_presets(presets_dict: dict, range_min_temp: int, range_max_temp: int) -> dict:
    """Clamp the temperature values in each preset within the specified range.

    Args:
        presets_dict (dict): A dictionary of presets where each value has a "temperature" key.
        range_min_temp (int): Minimum allowable temperature.
        range_max_temp (int): Maximum allowable temperature.

    Returns:
        dict: The updated presets dictionary with clamped temperatures.

    """
    for preset in presets_dict.values():
        preset["temperature"] = max(
            range_min_temp, min(preset["temperature"], range_max_temp)
        )
    return presets_dict


async def get_climate_group_nos(
    hass: HomeAssistant,
    entry_id: str,
    group_type: Literal["real", "virtual", "all"] = "real",
) -> list[str]:
    """Return a list of group_nos for 'real' climate devices (group_no between 1 and 128)."""
    registry = er.async_get(hass)
    # Get only the entries for this config entry
    entries = er.async_entries_for_config_entry(registry, entry_id)
    group_nos = []
    pattern = re.compile(f"^{re.escape(entry_id)}_(\\d+)_climate$")
    for entry in entries:
        if entry.platform != DOMAIN:  # filter by your integration domain if needed
            continue
        if match := pattern.match(entry.unique_id):
            try:
                group_no = int(match[1])
                match group_type:
                    case "real":
                        # Only include real devices (group_no 1-128)
                        if MIN_GROUP_NO <= group_no <= MAX_GROUP_NO:
                            group_nos.append(str(group_no))
                    case "virtual":
                        # Only include virtual devices (group_no 129-254)
                        if group_no > MAX_GROUP_NO:
                            group_nos.append(str(group_no))
                    case "all":
                        group_nos.append(str(group_no))
            except ValueError:
                continue
    return group_nos


async def get_climate_entities(hass: HomeAssistant, entry_id: str) -> list[str]:
    """Return a list of entity_ids for 'real' climate devices (group_no 1-128), sorted by entity name."""
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry_id)
    pattern = re.compile(f"^{re.escape(entry_id)}_(\\d+)_climate$")
    filtered = []
    for entry in entries:
        # Optionally filter by platform
        if entry.platform != DOMAIN:
            continue
        if match := pattern.match(entry.unique_id):
            try:
                group_no = int(match[1])
                if 1 <= group_no <= 128:
                    # Use entry.name for sorting; fallback to entry.entity_id if name is not set
                    filtered.append((entry.name or entry.entity_id, entry.entity_id))
            except ValueError:
                continue
    # Sort by the entity's name
    filtered.sort(key=lambda tup: tup[0])
    return [entity_id for _, entity_id in filtered]


def sanitize_groups_cfg(
    groups_cfg: dict[str, dict[str, str]], available_units: list[str]
) -> dict[str, dict[str, str]]:
    """Sanitize the group configuration.

    Validates the provided groups configuration against available units and removes invalid or duplicate groups.
    Raises GroupCfgInvalidException if no valid groups remain after sanitization.
    Raises GroupCfgWarning if some groups were invalid but some valid groups remain.

    Args:
        groups_cfg (dict): The group configuration to sanitize.
        available_units (list): List of available unit IDs.

    Returns:
        dict: The sanitized group configuration.

    Raises:
        GroupCfgInvalidException: If no valid groups remain.
        GroupCfgWarning: If some groups were invalid but some remain.

    """
    if not groups_cfg:
        return {}
        # raise GroupCfgInvalidException("No groups provided")

    sanitized = {}
    seen_unit_sets = set()  # to track unique sets of units (order-insensitive)
    removed_count = 0
    total_groups = len(groups_cfg)

    for group_id, group in groups_cfg.items():
        original_units = group.get("units", [])

        # Remove duplicates while preserving order.
        unique_units = []
        for unit in original_units:
            if unit not in unique_units:
                unique_units.append(unit)

        # Filter out any units not in available_units.
        valid_units = [unit for unit in unique_units if unit in available_units]

        # Each group must have at least 2 valid units.
        if len(valid_units) < 2:
            removed_count += 1
            continue

        # A group cannot contain all available units.
        if set(valid_units) == set(available_units):
            removed_count += 1
            continue

        # Create a key representing the unique set of units (order-insensitive).
        unit_set_key = tuple(sorted(valid_units, key=int))
        if unit_set_key in seen_unit_sets:
            removed_count += 1
            continue
        seen_unit_sets.add(unit_set_key)

        # Group is valid; add to sanitized dictionary.
        sanitized[group_id] = {"name": group.get("name", ""), "units": valid_units}

    valid_groups = len(sanitized)

    if valid_groups == 0:
        # If no groups are valid, this is a fatal error.
        raise GroupCfgInvalidException("All configurable groups invalid")

    if valid_groups < total_groups:
        message = (
            f"Out of {total_groups} groups, {valid_groups} group(s) are valid, "
            f"and {removed_count} group(s) were removed due to errors."
        )
        # Raise a warning exception carrying the sanitized groups.
        raise GroupCfgWarning(sanitized, message)

    # If all groups are valid, simply return the sanitized dictionary.
    return sanitized


def normalize_dict(d):
    """Normalize a dictionary by recursively processing string values.

    This function attempts to parse string values as JSON. If successful, and the parsed
    value is a list, it sorts the list and converts it to a tuple. This ensures that
    the order of elements in lists doesn't affect dictionary comparisons.

    Args:
        d (dict): The dictionary to normalize.

    Returns:
        dict: The normalized dictionary.

    """
    new_d = {}
    for key, value in d.items():
        if isinstance(value, dict):
            new_d[key] = normalize_dict(value)
        elif isinstance(value, str):
            try:
                parsed = json.loads(value)
                # If it's a list, sort it so order doesn't matter and convert to tuple (hashable)
                new_d[key] = (
                    tuple(sorted(parsed)) if isinstance(parsed, list) else value
                )
            except (json.JSONDecodeError, TypeError):
                new_d[key] = value
        else:
            new_d[key] = value
    return new_d


def generate_friendy_name(
    group_no: str | None,
    group_name: str | None,
    entity: str,
    main_entity: bool,
    stable: bool,
) -> str:
    """Generate a friendly name for an entity."""
    prefix = (
        (f"Group {group_no}" if group_no else "Group")
        if stable
        else (group_name.title() if group_name else "Name")
    )
    suffix = "" if main_entity else f" {ENTITY_SUFFIXES[entity]['friendly_name']}"
    return f"{prefix}{suffix}"


def generate_unique_id(
    entry_id: str,
    group_no: str | None,
    entity: str,
) -> str | None:
    """Generate a unique ID for an entity."""
    if not group_no:
        return None
    return f"{entry_id}_{(group_no)}_{ENTITY_SUFFIXES[entity]['unique_id']}"


def get_translation_key(
    entity: str,
) -> str:
    """Get translation_key for an entity."""
    return f"{DOMAIN}_{ENTITY_SUFFIXES[entity]['unique_id']}"
