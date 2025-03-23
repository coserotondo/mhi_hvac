"""Handles the options flow for the MHI HVAC integration."""

from copy import deepcopy
import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components.climate import ATTR_MAX_TEMP, ATTR_MIN_TEMP
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_SCAN_INTERVAL

from .const import (
    ALL_UNITS_GROUP_NO,
    CONF_GROUPS,
    CONF_HVAC_MODE_ACTIVE,
    CONF_HVAC_MODES,
    CONF_PRESETS,
    DEFAULT_SCAN_INTERVAL,
    NUM_CONFIGURED_GROUPS,
    TEMPERATURE_UNIT,
)
from .helpers import (
    GroupCfgInvalidException,
    GroupCfgWarning,
    clamp_presets,
    get_climate_group_nos,
    sanitize_groups_cfg,
)
from .pymhihvac.const import DEFAULT_FAN_MODE, DEFAULT_SWING_MODE, MAX_TEMP, MIN_TEMP
from .pymhihvac.utils import raise_vol_invalid
from .schemas import (
    PRESET_NAME_PATTERN,
    UNITS_LIST_PATTERN,
    edit_group_schema,
    edit_hvac_modes_schema,
    edit_preset_schema,
    general_settings_schema,
    hvac_modes_menu_schema,
    presets_menu_schema,
)

_LOGGER = logging.getLogger(__name__)


class OptionsFlowHandler(OptionsFlow):
    """Handle options flow for the MHI HVAC integration."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self.entry_id = config_entry.entry_id
        # Load persistent options (or default to an empty dict)
        self.options = deepcopy(dict(config_entry.options))
        self.editing_preset = None
        self.editing_hvac_modes = None
        # Ensure presets exists in options
        if CONF_HVAC_MODES not in self.options:
            self.options[CONF_HVAC_MODES] = {}
        if CONF_HVAC_MODE_ACTIVE not in self.options:
            self.options[CONF_HVAC_MODE_ACTIVE] = ""
        if CONF_PRESETS not in self.options:
            self.options[CONF_PRESETS] = {}
        if CONF_GROUPS not in self.options:
            self.options[CONF_GROUPS] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show main options menu with three choices."""
        menu_options = [
            "general_settings",
            "group_settings",
            "hvac_modes_settings",
            "preset_settings",
            "done",
        ]
        if user_input is not None:
            next_step = user_input.get("next_step_id")
            if next_step == "done":
                return await self.async_step_done()
            return await getattr(self, f"async_step_{next_step}")()

        # Build a summary description of current settings.
        description = (
            f"Scan Interval: {self.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)}s\n"
            f"Min Temp: {self.options.get(ATTR_MIN_TEMP, MIN_TEMP)}{TEMPERATURE_UNIT}\n"
            f"Max Temp: {self.options.get(ATTR_MAX_TEMP, MAX_TEMP)}{TEMPERATURE_UNIT}\n"
            f"Groups: {len(self.options.get('groups', {}))}\n"
            f"Presets: {len(self.options.get('presets', {}))}"
        )
        return self.async_show_menu(
            step_id="init",
            menu_options=menu_options,
            description_placeholders={"current_settings": description},
        )

    async def async_step_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finalize the options flow and persist options to disk."""
        hvac_modes = self.options.get(CONF_HVAC_MODES, {})
        hvac_modes_active = self.options.get(CONF_HVAC_MODE_ACTIVE, "")
        presets = self.options.get(CONF_PRESETS, {})
        groups = self.options.get(CONF_GROUPS, {})
        min_temp = self.options.get(
            ATTR_MIN_TEMP, self.options.get(ATTR_MIN_TEMP, MIN_TEMP)
        )
        max_temp = self.options.get(
            ATTR_MAX_TEMP, self.options.get(ATTR_MAX_TEMP, MAX_TEMP)
        )
        # Clamp preset temperatures using the helper.
        clamped_presets = clamp_presets(presets, min_temp, max_temp)
        self.options[CONF_PRESETS] = clamped_presets
        final_options = {
            CONF_SCAN_INTERVAL: self.options.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
            ),
            ATTR_MIN_TEMP: min_temp,
            ATTR_MAX_TEMP: max_temp,
            CONF_HVAC_MODES: hvac_modes,
            CONF_HVAC_MODE_ACTIVE: hvac_modes_active,
            CONF_PRESETS: clamped_presets,
            CONF_GROUPS: groups,
        }
        return self.async_create_entry(title="", data=final_options)

    async def async_step_general_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle core settings (scan interval and temperature ranges)."""
        errors = {}
        current = self.options
        if user_input is not None:
            try:
                if user_input.get(ATTR_MIN_TEMP, "") > user_input.get(
                    ATTR_MAX_TEMP, ""
                ):
                    raise_vol_invalid("invalid_min_temp")
                self.options.update(user_input)
                return await self.async_step_init()
            except vol.Invalid as e:
                errors["base"] = str(e)

        return self.async_show_form(
            step_id="general_settings",
            data_schema=general_settings_schema(current),
            errors=errors,
        )

    async def async_step_preset_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry point for preset management."""
        return await self.async_step_presets_menu(user_input)

    async def async_step_hvac_modes_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry point for HVAC modes management."""
        return await self.async_step_hvac_modes_menu(user_input)

    # async def async_step_presets_menu(self, user_input=None):
    async def async_step_presets_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Preset management menu to add, edit, or delete presets."""
        errors = {}
        presets = self.options.get(CONF_PRESETS, {})
        schema = presets_menu_schema(presets)

        if user_input and "action" in user_input:
            if "Add" in user_input["action"]:
                if len(presets) == 5:
                    errors["base"] = "max_presets"
                else:
                    self.editing_preset = ""
                    return await self.async_step_edit_preset()
            elif "Back" in user_input["action"]:
                return await self.async_step_init()
            elif "select_preset" in user_input:
                if "Edit" in user_input["action"]:
                    self.editing_preset = user_input["select_preset"]
                    return await self.async_step_edit_preset()
                if "Delete" in user_input["action"]:
                    del presets[user_input["select_preset"]]
                    self.options[CONF_PRESETS] = presets
                    return await self.async_step_presets_menu()
            else:
                errors["base"] = "missing_preset"

        # Build a textual summary of the presets.
        if not presets:
            description = "No presets configured"
        else:
            order = ["hvac_mode", "onoff_mode", "temperature", "fan_mode", "swing_mode"]
            lines = []
            for _name, _preset in presets.items():
                formatted_fields = [
                    str(_preset.get(key, "")).capitalize() for key in order
                ]
                lines.append(f"- {_name}: {' | '.join(formatted_fields)}")
            description = "\n".join(lines)

        return self.async_show_form(
            step_id="presets_menu",
            data_schema=schema,
            description_placeholders={CONF_PRESETS: description},
            errors=errors,
        )

    async def async_step_hvac_modes_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """HVAC modes management menu to add, edit, or delete HVAC modes."""
        errors = {}
        hvac_modes_active = self.options.get(CONF_HVAC_MODE_ACTIVE, "")
        hvac_modes = self.options.get(CONF_HVAC_MODES, {})
        schema = hvac_modes_menu_schema(hvac_modes, hvac_modes_active)

        if user_input and "action" in user_input:
            if "Add" in user_input["action"]:
                if len(hvac_modes) == 5:
                    errors["base"] = "max_hvac_modes"
                else:
                    self.editing_hvac_modes = ""
                    return await self.async_step_edit_hvac_modes()
            elif "Back" in user_input["action"]:
                return await self.async_step_init()
            elif "select_hvac_modes" in user_input:
                if "Edit" in user_input["action"]:
                    self.editing_hvac_modes = user_input["select_hvac_modes"]
                    return await self.async_step_edit_hvac_modes()
                if "Delete" in user_input["action"]:
                    del hvac_modes[user_input["select_hvac_modes"]]
                    if (
                        self.options[CONF_HVAC_MODE_ACTIVE]
                        == user_input["select_hvac_modes"]
                    ):
                        self.options[CONF_HVAC_MODE_ACTIVE] = ""
                    self.options[CONF_HVAC_MODES] = hvac_modes
                    return await self.async_step_hvac_modes_menu()
            elif "select_hvac_modes_active" in user_input:
                if "Set Active" in user_input["action"]:
                    self.options[CONF_HVAC_MODE_ACTIVE] = user_input[
                        "select_hvac_modes_active"
                    ]
                    return await self.async_step_init()
            else:
                errors["base"] = "missing_hvac_modes"

        if not hvac_modes:
            description = "No HVAC modes configured"
        else:
            description_lines = []
            for key in sorted(hvac_modes.keys()):
                if modes := hvac_modes[key].get(CONF_HVAC_MODES, []):
                    modes_titled = ", ".join(
                        mode.replace("_", " ").title() for mode in modes
                    )
                    description_lines.append(f"- {key}: {modes_titled}")
                else:
                    description_lines.append(f"{key}: No HVAC modes configured")
            description = "\n".join(description_lines)

        return self.async_show_form(
            step_id="hvac_modes_menu",
            data_schema=schema,
            description_placeholders={CONF_HVAC_MODES: description},
            errors=errors,
        )

    async def async_step_edit_hvac_modes(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit or create a preset."""
        errors = {}
        hvac_modes = self.options.get(CONF_HVAC_MODES, {})
        current_name = self.editing_hvac_modes or ""
        current_values = hvac_modes.get(
            current_name,
            {
                CONF_HVAC_MODES: [],
            },
        )
        current_values.setdefault("name", current_name)
        if user_input:
            try:
                if not re.match(PRESET_NAME_PATTERN, user_input["name"]):
                    raise_vol_invalid("hvac_modes_name_invalid")
                if user_input["name"]:
                    user_input["name"] = user_input["name"].title()
                if (
                    user_input["name"] in hvac_modes
                    and user_input["name"] != current_name
                ):
                    raise_vol_invalid("hvac_modes_name_exists")
                if current_name:
                    del hvac_modes[current_name]
                hvac_modes[user_input["name"]] = {
                    CONF_HVAC_MODES: user_input[CONF_HVAC_MODES],
                }
                self.options[CONF_HVAC_MODES] = hvac_modes
                return await self.async_step_hvac_modes_menu()

            except vol.Invalid as e:
                errors["base"] = str(e)

        return self.async_show_form(
            step_id="edit_hvac_modes",
            data_schema=edit_hvac_modes_schema(current_values),
            errors=errors,
            description_placeholders={
                "edit_mode": "Editing" if self.editing_hvac_modes else "New",
            },
        )

    async def async_step_edit_preset(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit or create a preset."""
        errors = {}
        presets = self.options.get(CONF_PRESETS, {})
        min_temp = self.options.get(ATTR_MIN_TEMP, MIN_TEMP)
        max_temp = self.options.get(ATTR_MAX_TEMP, MAX_TEMP)
        current_name = self.editing_preset or ""
        current_values = presets.get(
            current_name,
            {
                "hvac_mode": "",
                "onoff_mode": "",
                "temperature": int((min_temp + max_temp) / 2),
                "fan_mode": DEFAULT_FAN_MODE,
                "swing_mode": DEFAULT_SWING_MODE,
            },
        )
        # Ensure the preset has a "name" key (if not, set it to the preset's key).
        current_values.setdefault("name", current_name)

        if user_input:
            try:
                if not re.match(PRESET_NAME_PATTERN, user_input["name"]):
                    raise_vol_invalid("preset_name_invalid")
                if user_input["name"]:
                    user_input["name"] = user_input["name"].title()
                if user_input["name"] in presets and user_input["name"] != current_name:
                    raise_vol_invalid("preset_name_exists")
                if not (min_temp <= user_input["temperature"] <= max_temp):
                    raise_vol_invalid("temperature_out_of_range")
                if current_name:
                    del presets[current_name]
                presets[user_input["name"]] = {
                    "hvac_mode": user_input["hvac_mode"],
                    "onoff_mode": user_input.get("onoff_mode"),
                    "temperature": user_input["temperature"],
                    "fan_mode": user_input["fan_mode"],
                    "swing_mode": user_input["swing_mode"],
                }
                self.options[CONF_PRESETS] = presets
                return await self.async_step_presets_menu()

            except vol.Invalid as e:
                errors["base"] = str(e)

        return self.async_show_form(
            step_id="edit_preset",
            data_schema=edit_preset_schema(current_values, min_temp, max_temp),
            errors=errors,
            description_placeholders={
                "edit_mode": "Editing" if self.editing_preset else "New",
            },
        )

    async def async_step_group_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage group settings.

        Allows the user to configure and manage groups of units.
        """
        errors = {}
        groups = self.options.get(CONF_GROUPS, {})
        group_nos = await get_climate_group_nos(self.hass, self.entry_id)

        # Helper to build groups from user input.
        def build_groups_to_validate(user_input: dict[str, Any]) -> dict:
            groups_to_validate = {}
            for i in range(1, NUM_CONFIGURED_GROUPS + 1):
                group_no = ALL_UNITS_GROUP_NO + i
                group_data = user_input.get(f"group_no_{group_no}", {})
                group_name = group_data.get("name", "").title()
                unit_group_nos = group_data.get("units")
                if unit_group_nos and not re.match(UNITS_LIST_PATTERN, unit_group_nos):
                    raise_vol_invalid("unit_group_nos_invalid")
                if group_no and group_name and unit_group_nos:
                    groups_to_validate[str(group_no)] = {
                        "name": group_name,
                        "units": [u.strip() for u in unit_group_nos.split(",")],
                    }
                else:
                    groups.pop(str(group_no), None)
            return groups_to_validate

        # Helper to format configured groups for display.
        def format_configured_groups(groups: dict) -> str:
            if not groups:
                return "No groups configured"
            list_groups = [
                f"{key} | {value['name']} | ({'All' if key == str(ALL_UNITS_GROUP_NO) else ', '.join(value['units'])})"
                for key, value in sorted(groups.items(), key=lambda kv: int(kv[0]))
            ]
            return "\n".join(list_groups)

        if user_input:
            try:
                groups_to_validate = build_groups_to_validate(user_input)
                all_units_name = user_input.get("all_units_name", "").title()

                try:
                    valid_groups = sanitize_groups_cfg(groups_to_validate, group_nos)
                    groups = valid_groups or groups
                except GroupCfgWarning as warn:
                    errors["base"] = warn.message
                    groups = warn.sanitized_groups
                except GroupCfgInvalidException as e:
                    errors["base"] = str(e)
                    groups = {}

                if all_units_name:
                    groups[str(ALL_UNITS_GROUP_NO)] = {
                        "name": all_units_name,
                        "units": "all",
                    }
                else:
                    groups.pop(str(ALL_UNITS_GROUP_NO), None)

                self.options[CONF_GROUPS] = groups

                if not errors:
                    return await self.async_step_init()
            except vol.Invalid as e:
                errors["base"] = str(e)

        available_units = (
            ", ".join(group_nos)
            if isinstance(group_nos, list)
            else "No units available"
        )
        configured_groups = format_configured_groups(groups)

        return self.async_show_form(
            step_id="group_settings",
            data_schema=edit_group_schema(groups, NUM_CONFIGURED_GROUPS),
            errors=errors,
            description_placeholders={
                "available_units": available_units,
                "configured_groups": configured_groups,
            },
        )
