"""Sensor platform for My HVAC System integration."""

import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .helpers import generate_friendy_name, generate_unique_id
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
        MHIHVACRoomTempSensorEntity(device_data, coordinator, entry_id)
        for device_data in devices_data
    ]

    async_add_entities(devices)


class MHIHVACRoomTempSensorEntity(CoordinatorEntity, SensorEntity):  # type: ignore[reportIncompatibleVariableOverride]
    """Temperature sensor for HVAC unit."""

    coordinator: "MHIHVACDataUpdateCoordinator"
    device_data: "MHIHVACDeviceData"

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True

    def __init__(
        self,
        device_data: "MHIHVACDeviceData",
        coordinator: "MHIHVACDataUpdateCoordinator",
        entry_id: str,
    ) -> None:
        """Initialize with HVAC unit."""
        super().__init__(coordinator)
        self.device_data = device_data
        self._attr_device_info = coordinator.device_info
        # self._attr_unique_id = f"{entry_id}_{device_data.group_no}_{ENTITY_SUFFIXES[self.__class__.__name__]['unique_id']}"
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
        self._attr_native_value = self.device_data.current_temperature
        self._attr_extra_state_attributes["group_no"] = self.device_data.group_no
        if self.device_data.is_virtual:
            self._attr_extra_state_attributes["all_real_unit_group_nos"] = (
                self.device_data.all_real_unit_group_nos
            )

    async def async_added_to_hass(self) -> None:
        """Register callbacks and update entity name when added to hass.

        This method is called when the entity is added to Home Assistant. It registers
        a listener for coordinator updates and sets the initial name of the entity
        if available.
        """
        await super().async_added_to_hass()
        _LOGGER.debug(
            "Sensor entity async_added_to_hass for group_no: %s",
            self.device_data.group_no,
        )
        if self.device_data.group_name:
            _LOGGER.debug(
                "Updating sensor entity friendly_name with new device_data for group_no: %s",
                self.device_data.group_no,
            )
            # self._attr_name = f"{self.device_data.group_name.title()} Room Temperature"
            self._attr_name = generate_friendy_name(
                group_no=self.device_data.group_no,
                group_name=self.device_data.group_name,
                entity=self.__class__.__name__,
                main_entity=False,
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
                "Could not find updated device_data for group_no: %s in coordinator data",
                self.device_data.group_no,
            )
