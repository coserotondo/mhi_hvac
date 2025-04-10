"""Schemas and regex patterns for the MHI HVAC integration."""

import logging
from typing import Any

from pymhihvac.const import (
    DEFAULT_FAN_MODE,
    DEFAULT_SWING_MODE,
    MAX_TEMP,
    MHI_FAN_MODES,
    MHI_HVAC_SET_MODES,
    MHI_LOCK_MODES,
    MHI_ONOFF_MODES,
    MHI_SWING_MODES,
    MIN_TEMP,
    RAW_DATA_REQUEST_KEY_MAPPING,
)
import voluptuous as vol

from homeassistant.components.climate import ATTR_MAX_TEMP, ATTR_MIN_TEMP
from homeassistant.const import (
    CONF_HOST,
    CONF_MODEL_ID,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import selector

from .const import (
    ALL_UNITS_GROUP_NO,
    CONF_HVAC_MODES,
    CONF_INCLUDE_GROUPS,
    CONF_INCLUDE_INDEX,
    CONF_METHOD,
    CONF_SERIAL_NUMBER,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MHI_HVAC_MODES,
    TEMPERATURE_UNIT,
)
from .utils import join_if_list

# Regex patterns
IPV4_PATTERN = r"^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
HOSTNAME_PATTERN = r"^([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])(\.([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]{0,61}[a-zA-Z0-9]))*$"
USERNAME_PATTERN = r"(?i)^[a-z0-9]+$"
SERIAL_NUMBER_PATTERN = r"^\S+$"
PRESET_NAME_PATTERN = r"(?i)^[a-z0-9]+$"
UNITS_LIST_PATTERN = r"^[1-9]\d*(?:,\s*[1-9]\d*)+$"
BLOCKS_LIST_PATTERN = UNITS_LIST_PATTERN

# Base schema for initial configuration.
DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_MODEL_ID): cv.string,
        vol.Required(CONF_SERIAL_NUMBER): cv.string,
        vol.Required(CONF_METHOD): selector(
            {
                "select": {
                    "options": [
                        {"value": m, "label": m.capitalize()}
                        for m in RAW_DATA_REQUEST_KEY_MAPPING
                    ],
                    "mode": "list",
                }
            }
        ),
        vol.Optional(CONF_INCLUDE_INDEX): cv.string,
        vol.Optional(CONF_INCLUDE_GROUPS): cv.string,
    }
)

SERVICE_SET_PROPERTIES_SCHEMA = vol.Schema(
    {
        vol.Required("climate_entity"): selector(
            {
                "entity": {
                    "filter": {"integration": DOMAIN, "domain": "climate"},
                    "multiple": True,
                }
            }
        ),
        vol.Optional("hvac_mode"): selector(
            {
                "select": {
                    "options": [
                        {"value": m, "label": m.capitalize()}
                        for m in MHI_HVAC_SET_MODES
                    ],
                    "mode": "dropdown",
                }
            }
        ),
        vol.Optional("onoff_mode"): selector(
            {
                "select": {
                    "options": [
                        {"value": m, "label": m.capitalize()} for m in MHI_ONOFF_MODES
                    ],
                    "mode": "list",
                }
            }
        ),
        vol.Optional("target_temperature"): selector(
            {
                "number": {
                    "min": MIN_TEMP,
                    "max": MAX_TEMP,
                    "step": 0.5,
                    "mode": "box",
                    "unit_of_measurement": TEMPERATURE_UNIT,
                }
            }
        ),
        vol.Optional("fan_mode"): selector(
            {
                "select": {
                    "options": [
                        {"value": m, "label": m.capitalize()} for m in MHI_FAN_MODES
                    ],
                    "mode": "dropdown",
                }
            }
        ),
        vol.Optional("swing_mode"): selector(
            {
                "select": {
                    "options": [
                        {"value": m, "label": m.capitalize()} for m in MHI_SWING_MODES
                    ],
                    "mode": "dropdown",
                }
            }
        ),
        vol.Optional("filter_reset"): selector({"boolean": {}}),
        vol.Optional("lock_mode"): selector(
            {
                "select": {
                    "options": [
                        {"value": m, "label": m.capitalize()} for m in MHI_LOCK_MODES
                    ],
                    "mode": "dropdown",
                }
            }
        ),
    }
)


SERVICE_SET_ACTIVE_HVAC_MODES_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): selector(
            {
                "config_entry": {"integration": DOMAIN},
            }
        ),
        vol.Required("new_active_mode"): cv.string,
    }
)


_LOGGER = logging.getLogger(__name__)


def reconfigure_schema(current_values: dict) -> vol.Schema:
    """Return the schema for the reconfigure step menu form."""
    include_index = join_if_list(current_values.get(CONF_INCLUDE_INDEX))
    include_groups = join_if_list(current_values.get(CONF_INCLUDE_GROUPS))
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=current_values.get(CONF_HOST)): cv.string,
            vol.Required(
                CONF_USERNAME, default=current_values.get(CONF_USERNAME)
            ): cv.string,
            vol.Required(
                CONF_PASSWORD, default=current_values.get(CONF_PASSWORD)
            ): cv.string,
            vol.Required(
                CONF_METHOD, default=current_values.get(CONF_METHOD)
            ): selector(
                {
                    "select": {
                        "options": [
                            {"value": m, "label": m.capitalize()}
                            for m in RAW_DATA_REQUEST_KEY_MAPPING
                        ],
                        "mode": "list",
                    }
                }
            ),
            vol.Optional(
                CONF_INCLUDE_INDEX,
                description={"suggested_value": include_index},
            ): cv.string,
            vol.Optional(
                CONF_INCLUDE_GROUPS,
                description={"suggested_value": include_groups},
            ): cv.string,
        }
    )


def general_settings_schema(current_values: dict) -> vol.Schema:
    """Return the schema for general (core) settings."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=current_values.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): selector(
                {
                    "number": {
                        "min": 5,
                        "max": 600,
                        "step": 1,
                        "mode": "box",
                    }
                }
            ),
            vol.Optional(
                ATTR_MIN_TEMP,
                default=current_values.get(ATTR_MIN_TEMP, MIN_TEMP),
            ): selector(
                {
                    "number": {
                        "min": MIN_TEMP,
                        "max": MAX_TEMP,
                        "step": 1,
                        "mode": "box",
                        "unit_of_measurement": TEMPERATURE_UNIT,
                    }
                }
            ),
            vol.Optional(
                ATTR_MAX_TEMP,
                default=current_values.get(ATTR_MAX_TEMP, MAX_TEMP),
            ): selector(
                {
                    "number": {
                        "min": MIN_TEMP,
                        "max": MAX_TEMP,
                        "step": 1,
                        "mode": "box",
                        "unit_of_measurement": TEMPERATURE_UNIT,
                    }
                }
            ),
        }
    )


def presets_menu_schema(presets: dict) -> vol.Schema:
    """Return the schema for the presets menu form."""
    return vol.Schema(
        {
            vol.Optional("action"): selector(
                {
                    "select": {
                        "options": ["Add", "Edit", "Delete", "Back"],
                        "mode": "list",
                    }
                }
            ),
            vol.Optional("select_preset"): selector(
                {
                    "select": {
                        "options": list(presets.keys()),
                        "mode": "dropdown",
                        "sort": True,
                    }
                }
            ),
        }
    )


def hvac_modes_menu_schema(
    hvac_modes: dict, hvac_modes_active: str | None
) -> vol.Schema:
    """Return the schema for the HVAC modes menu form."""
    return vol.Schema(
        {
            vol.Optional("action"): selector(
                {
                    "select": {
                        "options": ["Add", "Edit", "Delete", "Set Active", "Back"],
                        "mode": "list",
                    }
                }
            ),
            vol.Optional("select_hvac_modes"): selector(
                {
                    "select": {
                        "options": list(hvac_modes.keys()),
                        "mode": "dropdown",
                        "sort": True,
                    }
                }
            ),
            vol.Optional(
                "select_hvac_modes_active",
                description={"suggested_value": hvac_modes_active},
            ): selector(
                {
                    "select": {
                        "options": list(hvac_modes.keys()),
                        "mode": "dropdown",
                        "sort": True,
                    }
                }
            ),
        }
    )


def edit_hvac_modes_schema(current_values: dict) -> vol.Schema:
    """Return the schema for editing HVAC modes.

    Creates a schema for editing available HVAC modes, allowing users to select
    multiple modes from a predefined list.
    """
    return vol.Schema(
        {
            vol.Required("name", default=current_values.get("name")): cv.string,
            vol.Required(
                CONF_HVAC_MODES,
                default=current_values.get(CONF_HVAC_MODES),
            ): selector(
                {
                    "select": {
                        "options": [
                            {"value": m, "label": m.capitalize()}
                            for m in MHI_HVAC_MODES
                        ],
                        "multiple": True,
                    }
                }
            ),
        }
    )


def edit_preset_schema(
    current_values: dict, min_temp: int, max_temp: int
) -> vol.Schema:
    """Return the schema for editing/adding a preset."""
    # Use defaults from current_values or fall back to standard defaults.
    default_temp = current_values.get("temperature", int((min_temp + max_temp) / 2))
    return vol.Schema(
        {
            vol.Required("name", default=current_values.get("name")): cv.string,
            vol.Required(
                "hvac_mode", default=current_values.get("hvac_mode")
            ): selector(
                {
                    "select": {
                        "options": [
                            {"value": m, "label": m.capitalize()}
                            for m in MHI_HVAC_SET_MODES
                        ],
                        "mode": "dropdown",
                    }
                }
            ),
            vol.Optional(
                "onoff_mode",
                description={"suggested_value": current_values.get("onoff_mode")},
            ): selector(
                {
                    "select": {
                        "options": [
                            {"value": m, "label": m.capitalize()}
                            for m in MHI_ONOFF_MODES
                        ],
                        "mode": "dropdown",
                    }
                }
            ),
            vol.Required("temperature", default=default_temp): selector(
                {
                    "number": {
                        "min": min_temp,
                        "max": max_temp,
                        "step": 1,
                        "mode": "box",
                        "unit_of_measurement": TEMPERATURE_UNIT,
                    }
                }
            ),
            vol.Required(
                "fan_mode", default=current_values.get("fan_mode", DEFAULT_FAN_MODE)
            ): selector(
                {
                    "select": {
                        "options": [
                            {"value": m, "label": m.capitalize()} for m in MHI_FAN_MODES
                        ],
                        "mode": "dropdown",
                    }
                }
            ),
            vol.Required(
                "swing_mode",
                default=current_values.get("swing_mode", DEFAULT_SWING_MODE),
            ): selector(
                {
                    "select": {
                        "options": [
                            {"value": m, "label": m.capitalize()}
                            for m in MHI_SWING_MODES
                        ],
                        "mode": "dropdown",
                    }
                }
            ),
        }
    )


def edit_group_schema(current_values: dict, num_groups: int) -> vol.Schema:
    """Return the schema for editing a group.

    Generates a schema for editing group settings, including names and unit assignments.
    It dynamically creates sections for each group based on the provided number of groups.
    """
    schema_dict: dict[Any, Any] = {
        vol.Optional(
            "all_units_name",
            description={
                "suggested_value": current_values.get(str(ALL_UNITS_GROUP_NO), {}).get(
                    "name", ""
                )
            },
        ): str,
    }
    for i in range(1, num_groups + 1):
        group_no = str(ALL_UNITS_GROUP_NO + i)
        default_name = current_values.get(group_no, {}).get("name", "")
        default_units = join_if_list(current_values.get(group_no, {}).get("units", ""))
        group_schema = vol.Schema(
            {
                vol.Optional(
                    "name", description={"suggested_value": default_name}
                ): str,
                vol.Optional(
                    "units", description={"suggested_value": default_units}
                ): str,
            }
        )
        schema_dict[vol.Required(f"group_no_{group_no}")] = section(
            group_schema,
            {"collapsed": True},
        )
    return vol.Schema(schema_dict)
