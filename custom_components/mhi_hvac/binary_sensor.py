"""Provides binary sensor entities for the MHI HVAC integration.

Classes:
    MHIHVACFilterSensor: Represents a binary sensor for the filter sign of an MHI HVAC group.
    MHIHVACRCLockSensor: Represents a binary sensor for the remote control lock status of an MHI HVAC group.
"""

import logging
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .helpers import generate_friendy_name, generate_unique_id, get_translation_key
from .utils import raise_config_entry_not_ready

if TYPE_CHECKING:
    from .coordinator import MHIHVACDataUpdateCoordinator, MHIHVACDeviceData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: MHIHVACDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    coordinator.config_entry = config_entry
    entry_id: str = config_entry.entry_id
    devices_data: list[MHIHVACDeviceData] = []
    try:
        devices_data = coordinator.devices_data
    except (KeyError, IndexError, TypeError) as e:
        raise_config_entry_not_ready("Failed to parse group data:", e)

    devices = [
        entity_class(device_data, coordinator, entry_id)
        for device_data in devices_data
        for entity_class in (MHIHVACFilterSensorEntity, MHIHVACRCLockSensorEntity)
    ]

    async_add_entities(devices)


class MHIHVACBaseBinarySensorEntity(CoordinatorEntity, BinarySensorEntity):  # type: ignore[reportIncompatibleVariableOverride]
    """Base class for MHI HVAC binary sensors."""

    coordinator: "MHIHVACDataUpdateCoordinator"
    device_data: "MHIHVACDeviceData"
    _attr_has_entity_name = True

    def __init__(self, device_data, coordinator, entry_id: str) -> None:
        """Initialize the sensor with common attributes."""
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
            main_entity=False,
            stable=True,
        )
        self._attr_extra_state_attributes = {}
        self._update_sensor_attributes()

    def _update_sensor_attributes(self) -> None:
        """Initialize additional sensor attributes for the entity."""
        _LOGGER.debug(
            "Starting _update_sensor_attributes for group_no: %s",
            self.device_data.group_no,
        )
        self._attr_available = self.coordinator.last_update_success and any(
            d.group_no == self.device_data.group_no
            for d in self.coordinator.devices_data
        )
        if not self._attr_available:
            return

        # Call subclass-specific method to set the sensor state
        self._attr_is_on = self._get_sensor_status()
        self._attr_extra_state_attributes["group_no"] = self.device_data.group_no
        if self.device_data.is_virtual:
            self._attr_extra_state_attributes["all_real_unit_group_nos"] = (
                self.device_data.all_real_unit_group_nos
            )

    def _get_sensor_status(self):
        """Abstract method: subclasses must implement to return the sensor's on/off state."""
        raise NotImplementedError("Subclasses must implement _get_sensor_status")

    async def async_added_to_hass(self) -> None:
        """Register callbacks and update entity name when added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug(
            "Sensor entity async_added_to_hass for group_no: %s",
            self.device_data.group_no,
        )
        if self.device_data.group_name:
            _LOGGER.debug(
                "Updating sensor entity friendly_name for group_no: %s",
                self.device_data.group_no,
            )
            self._attr_name = generate_friendy_name(
                group_no=self.device_data.group_no,
                group_name=self.device_data.group_name,
                entity=self.__class__.__name__,
                main_entity=False,
                stable=False,
            )
            self.async_write_ha_state()
        # Subscribe to coordinator updates
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug(
            "Sensor entity _handle_coordinator_update for group_no: %s",
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
                main_entity=False,
                stable=False,
            )
            if updated_device_data.group_name and self._attr_name != friendly_name:
                self._attr_name = friendly_name
            self.device_data = updated_device_data
            self._update_sensor_attributes()
            self.async_write_ha_state()
        else:
            _LOGGER.warning(
                "Could not find updated device_data for group_no: %s",
                self.device_data.group_no,
            )


class MHIHVACFilterSensorEntity(MHIHVACBaseBinarySensorEntity):
    """Binary sensor that monitors the filter status of an MHI HVAC system."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def _get_sensor_status(self):
        """Return filter sensor status."""
        return self.device_data.is_filter_sign


class MHIHVACRCLockSensorEntity(MHIHVACBaseBinarySensorEntity):
    """Binary sensor that monitors the remote control lock status of an MHI HVAC system."""

    _attr_device_class = BinarySensorDeviceClass.LOCK

    def _update_sensor_attributes(self) -> None:
        """Update sensor attributes, including the extended RC lock state."""
        # First, update the common attributes from the base class.
        super()._update_sensor_attributes()
        # Now add the extended lock attribute from the device data.
        self._attr_extra_state_attributes["rc_lock_extended"] = (
            self.device_data.rc_lock_extended
        )

    def _get_sensor_status(self):
        """Return RC lock sensor status."""
        return self.device_data.rc_lock
