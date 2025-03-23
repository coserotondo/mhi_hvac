"""Provides climate integration for Mitsubishi HVAC systems with Home Assistant.

This module implements the climate platform for the Mitsubishi HVAC integration,
allowing control of HVAC units as climate entities within Home Assistant.
"""

import logging
from typing import TYPE_CHECKING

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_HALVES
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MHI_HVAC_MODES, TEMPERATURE_UNIT
from .helpers import generate_friendy_name, generate_unique_id, get_translation_key
from .pymhihvac.const import (
    MHI_FAN_MODES,
    MHI_SWING_MODES,
    MHIFanMode,
    MHIHVACMode,
    MHIOnOffMode,
    MHISwingMode,
)
from .utils import raise_config_entry_not_ready

if TYPE_CHECKING:
    from .coordinator import MHIHVACDataUpdateCoordinator, MHIHVACDeviceData

SUPPORTED_FEATURES = (
    ClimateEntityFeature.TARGET_TEMPERATURE
    | ClimateEntityFeature.FAN_MODE
    | ClimateEntityFeature.SWING_MODE
    | ClimateEntityFeature.TURN_ON
    | ClimateEntityFeature.TURN_OFF
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate platform."""
    coordinator: MHIHVACDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    coordinator.config_entry = config_entry
    entry_id: str = config_entry.entry_id
    devices_data: list[MHIHVACDeviceData] = []
    try:
        devices_data = coordinator.devices_data
    except (KeyError, IndexError, TypeError) as e:
        raise_config_entry_not_ready("Failed to parse group data:", e)

    devices = [
        MHIHVACClimateEntity(device_data, coordinator, entry_id)
        for device_data in devices_data
    ]

    async_add_entities(devices)


class MHIHVACClimateEntity(CoordinatorEntity, ClimateEntity):  # type: ignore[reportIncompatibleVariableOverride]
    """Represent a Mitsubishi Heavy Industries HVAC unit in Home Assistant."""

    coordinator: "MHIHVACDataUpdateCoordinator"
    device_data: "MHIHVACDeviceData"

    _attr_available: bool = False
    _attr_temperature_unit: str = TEMPERATURE_UNIT
    _attr_precision: float = PRECISION_HALVES
    # _attr_supported_features = SUPPORTED_FEATURES
    _attr_has_entity_name: bool = True
    _enable_turn_on_off_backwards_compatibility: bool = False  # For deprecated features

    def __init__(
        self,
        device_data: "MHIHVACDeviceData",
        coordinator: "MHIHVACDataUpdateCoordinator",
        entry_id: str,
    ) -> None:
        """Initialize the HVAC unit with its GroupNo and GroupName."""
        super().__init__(coordinator)
        self._attr_translation_key = get_translation_key(self.__class__.__name__)
        self.device_data = device_data
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = generate_unique_id(
            entry_id=entry_id,
            group_no=device_data.group_no,
            entity=self.__class__.__name__,
        )
        self._attr_name = generate_friendy_name(
            group_no=device_data.group_no,
            group_name=device_data.group_name,
            entity=self.__class__.__name__,
            main_entity=True,
            stable=True,
        )
        self._attr_fan_modes = MHI_FAN_MODES
        self._attr_swing_modes = MHI_SWING_MODES
        self._presets = {}
        self._attr_preset_modes = None
        self._attr_preset_mode = None
        self._attr_extra_state_attributes = {}
        self._update_climate_attributes()

    def _update_hvac_valid_modes(self) -> None:
        if self.coordinator.hvac_modes_config is not None:
            self._attr_hvac_modes = [
                mode
                for mode in HVACMode
                if mode.value in self.coordinator.hvac_modes_config
            ]
        else:
            self._attr_hvac_modes = MHI_HVAC_MODES

    def _get_matching_preset(self) -> str | None:
        """Return the name of the preset that matches the current_attrs for the given keys, or None if no match is found."""
        current_attrs = {
            "fan_mode": self._attr_fan_mode,
            "hvac_mode": self.device_data.hvac_set_mode,
            "swing_mode": self._attr_swing_mode,
            "temperature": self._attr_target_temperature,
        }

        keys_to_match = ["fan_mode", "hvac_mode", "swing_mode", "temperature"]
        return next(
            (
                preset_name
                for preset_name, settings in self._presets.items()
                if all(
                    current_attrs.get(key) == settings.get(key) for key in keys_to_match
                )
            ),
            None,
        )

    def _update_presets(self) -> None:
        """Update preset modes and supported features."""
        # self._presets = self.coordinator.config_entry.options.get(CONF_PRESETS, {})
        self._presets = self.coordinator.presets
        if self._presets:
            self._attr_supported_features = (
                SUPPORTED_FEATURES | ClimateEntityFeature.PRESET_MODE
            )
            self._attr_preset_modes = list(self._presets.keys())
            self._attr_preset_mode = self._get_matching_preset()
        else:
            self._attr_supported_features = SUPPORTED_FEATURES

    def _update_climate_attributes(self) -> None:
        """Initialize additional climate attributes for the entity."""
        _LOGGER.debug(
            "Starting _update_climate_attributes for group_no: %s",
            self.device_data.group_no,
        )
        self._attr_available = self.coordinator.last_update_success and any(
            d.group_no == self.device_data.group_no
            for d in self.coordinator.devices_data
        )
        if not self._attr_available:
            return
        self._attr_current_temperature = self.device_data.current_temperature
        self._attr_target_temperature = self.device_data.target_temperature
        self._attr_fan_mode = self.device_data.fan_mode
        self._update_hvac_valid_modes()
        self._attr_hvac_mode = HVACMode(self.device_data.hvac_mode)
        self._attr_swing_mode = self.device_data.swing_mode
        self._attr_extra_state_attributes["group_no"] = self.device_data.group_no
        if self.device_data.is_virtual:
            self._attr_extra_state_attributes["all_real_unit_group_nos"] = (
                self.device_data.all_real_unit_group_nos
            )
            is_all_devices_group = self.device_data.is_all_devices_group or False
            self._attr_extra_state_attributes["is_all_devices_group"] = (
                is_all_devices_group
            )
        self._attr_extra_state_attributes["hvac_set_mode"] = (
            self.device_data.hvac_set_mode
        )
        self._attr_max_temp = self.coordinator.max_temp
        self._attr_min_temp = self.coordinator.min_temp
        self._update_presets()

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature optimistically."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        # Optimistically update the local state
        self._attr_target_temperature = temperature
        self.async_write_ha_state()

        # Perform the actual API call in the background
        await self.coordinator.async_set_device_property(
            "set_temperature", self.device_data, temperature
        )

    async def async_set_hvac_mode(self, hvac_mode) -> None:
        """Set new HVAC Mode."""
        self._attr_hvac_mode = HVACMode(hvac_mode)
        self.async_write_ha_state()
        await self.coordinator.async_set_device_property(
            "set_hvac_mode", self.device_data, MHIHVACMode(hvac_mode)
        )

    async def async_set_fan_mode(self, fan_mode) -> None:
        """Set new fan mode."""
        self._attr_fan_mode = MHIFanMode(fan_mode)
        self.async_write_ha_state()
        await self.coordinator.async_set_device_property(
            "set_fan_mode", self.device_data, MHIFanMode(fan_mode)
        )

    async def async_set_swing_mode(self, swing_mode) -> None:
        """Set new swing mode."""
        self._attr_swing_mode = MHISwingMode(swing_mode)
        self.async_write_ha_state()
        await self.coordinator.async_set_device_property(
            "set_swing_mode", self.device_data, MHISwingMode(swing_mode)
        )

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        await self.coordinator.async_set_device_property(
            "turn_hvac_on", self.device_data, self.device_data.hvac_set_mode
        )

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        await self.coordinator.async_set_device_property(
            "turn_hvac_off", self.device_data
        )

    async def async_set_preset_mode(self, preset_mode) -> None:
        """Set new target preset mode."""
        if preset_mode is None:
            return
        self._attr_preset_mode = preset_mode
        self.async_write_ha_state()
        preset_mode_title = preset_mode.title()
        _LOGGER.debug("Setting preset mode to: %s", preset_mode_title)
        preset = self._presets.get(preset_mode_title, {})

        hvac_mode = MHIHVACMode(preset.get("hvac_mode"))
        # self._preset_hvac_modes = [
        #     HVACMode(mode) for mode in preset.get(CONF_HVAC_MODES, [])
        # ]  # TODO: verify
        onoff_mode_raw = preset.get("onoff_mode")
        onoff_mode = (
            MHIOnOffMode(onoff_mode_raw) if onoff_mode_raw is not None else None
        )
        fan_mode = MHIFanMode(preset.get("fan_mode"))
        swing_mode = MHISwingMode(preset.get("swing_mode"))
        target_temperature = preset.get("temperature")

        # Build the parameters list conditionally.
        params = [hvac_mode, fan_mode, swing_mode, target_temperature]
        if onoff_mode is not None:
            params.append(onoff_mode)

        await self.coordinator.async_set_device_property(
            "set_preset_mode", self.device_data, *params
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks and update entity name when added to hass.

        This method is called when the entity is added to Home Assistant. It registers
        a listener for coordinator updates and sets the initial name of the entity
        if available.
        """
        await super().async_added_to_hass()
        _LOGGER.debug(
            "Climate entity async_added_to_hass for group_no: %s",
            self.device_data.group_no,
        )
        if self.device_data.group_name:
            _LOGGER.debug(
                "Updating climate entity friendly_name with new device_data for group_no: %s",
                self.device_data.group_no,
            )
            self._attr_name = generate_friendy_name(
                group_no=self.device_data.group_no,
                group_name=self.device_data.group_name,
                entity=self.__class__.__name__,
                main_entity=True,
                stable=False,
            )
            self.async_write_ha_state()
        # Subscribe to coordinator updates after entity is registered
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator.

        This method is called when the coordinator updates its data. It checks for
        updates to the device data and updates the entity's state accordingly.
        """
        _LOGGER.debug(
            "Climate entity _handle_coordinator_update for group_no: %s",
            self.device_data.group_no,
        )
        if updated_device_data := next(
            (
                device
                for device in self.coordinator.devices_data
                if device.group_no == self.device_data.group_no
            ),
            None,
        ):
            friendly_name = generate_friendy_name(
                group_no=updated_device_data.group_no,
                group_name=updated_device_data.group_name,
                entity=self.__class__.__name__,
                main_entity=True,
                stable=False,
            )
            if updated_device_data.group_name and self._attr_name != friendly_name:
                self._attr_name = friendly_name
            self.device_data = updated_device_data
            self._update_climate_attributes()
            self.async_write_ha_state()
        else:
            _LOGGER.warning(
                "Could not find updated device_data for group_no: %s in coordinator data",
                self.device_data.group_no,
            )
