"""Provides the MHICoordinator class with integrated helper functions."""

from datetime import timedelta
import json
import logging
from typing import Any

from aiohttp import ClientError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DEFAULT_MANUFACTURER, DEFAULT_MODEL, DOMAIN, ENTITY_SUFFIXES
from .pymhihvac.api import (
    ApiCallFailedException,
    LoginFailedException,
    NoSessionCookieException,
)
from .pymhihvac.controller import MHIHVACSystemController
from .pymhihvac.device import MHIHVACDeviceData, parse_raw_data
from .utils import raise_update_failed

_LOGGER = logging.getLogger(__name__)


class MHIHVACDataUpdateCoordinator(DataUpdateCoordinator):
    """Enhanced coordinator with config entry integration."""

    api_controller: MHIHVACSystemController
    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        name: str,
        session,
        host: str,
        username: str,
        password: str,
        model_id: str,
        serial_number: str,
        presets: dict,
        hvac_modes_config: list | None,
        virtual_group_config: dict,
        max_temp: float,
        min_temp: float,
        update_interval: timedelta,
    ) -> None:
        """Initialize DataUpdateCoordinator."""
        self.api_controller = MHIHVACSystemController(host, username, password, session)
        self.api_commands = {
            "set_temperature": self.api_controller.async_set_target_temperature,
            "set_hvac_mode": self.api_controller.async_set_hvac_mode,
            "set_fan_mode": self.api_controller.async_set_fan_mode,
            "set_swing_mode": self.api_controller.async_set_swing_mode,
            "turn_hvac_on": self.api_controller.async_turn_hvac_on,
            "turn_hvac_off": self.api_controller.async_turn_hvac_off,
            "set_preset_mode": self.api_controller.async_set_preset_mode,
            "set_device_property": self.api_controller.set_device_property,
        }
        self.devices_data: list[
            MHIHVACDeviceData
        ] = []  # Now a single list for all devices (units and virtual groups)
        self.presets = presets
        self.hvac_modes_config = hvac_modes_config
        self.max_temp = max_temp
        self.min_temp = min_temp
        self.virtual_group_config = virtual_group_config

        super().__init__(
            hass,
            logger=logger,
            name=name,
            update_interval=update_interval,
            always_update=True,
        )
        # self._is_shutdown = False  # Add shutdown flag
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, serial_number)},
            manufacturer=DEFAULT_MANUFACTURER,
            name=name,
            model=DEFAULT_MODEL,
            model_id=model_id,
            serial_number=serial_number,
            configuration_url=f"http://{host}",
        )

    # @property
    # def is_shutdown(self) -> str:
    #     """Return configured host."""
    #     return self._is_shutdown

    async def prune_stale_entities(self) -> None:
        """Remove entities from the registry that are no longer reported by the API."""
        registry = er.async_get(self.hass)

        valid_unique_ids = {
            f"{self.config_entry.entry_id}_{device.group_no}_{config['unique_id']}"
            for device in self.devices_data
            if device.group_no is not None
            for config in ENTITY_SUFFIXES.values()
        }

        entries = er.async_entries_for_config_entry(
            registry, self.config_entry.entry_id
        )
        # Iterate over a copy of the registry entities to avoid modification during iteration.
        for entry in entries:
            if entry.platform != DOMAIN:
                continue
            if entry.unique_id not in valid_unique_ids:
                _LOGGER.info("Removing stale entity: %s", entry.entity_id)
                registry.async_remove(entry.entity_id)

    # async def async_shutdown(self):
    #     """Cleanup coordinator resources."""
    #     if self._is_shutdown:
    #         return  # Prevent duplicate calls
    #     self._is_shutdown = True
    #     _LOGGER.debug("Coordinator for %s shutdown", self.host)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint asynchronously."""
        try:
            raw_data = await self.api_controller.async_update_data()
            raw_data_list: list[dict[str, Any]] = (
                raw_data if isinstance(raw_data, list) else []
            )
            devices_data: list[
                MHIHVACDeviceData
            ] = await self.hass.async_add_executor_job(
                parse_raw_data,
                raw_data_list,
                self.virtual_group_config,
            )
            self.devices_data = devices_data  # Store the single list of devices
            for device in self.devices_data:
                _LOGGER.debug(
                    "Found device with group_no '%s' and group_name '%s'",
                    device.group_no,
                    device.group_name,
                )
            # After updating data, prune entities that are no longer reported.
            await self.prune_stale_entities()
        except (
            ClientError,
            TimeoutError,
            json.JSONDecodeError,
            ApiCallFailedException,
            LoginFailedException,
            NoSessionCookieException,
        ) as e:
            raise_update_failed("Error updating data:", e)
            raise  # Ensure this branch never returns a value
        _LOGGER.debug("Raw data updated: %s", raw_data)
        return raw_data or {}

    async def async_service_call_set_device_property(
        self, group_no: int, payload: tuple[list[str], list[Any]]
    ) -> bool:
        """Execute a command on the HVAC device using the centralized command executor.

        This method sets properties on the device based on the provided payload.
        """
        # Retrieve the device data based on group_no
        device_data = next(
            (d for d in self.devices_data if d.group_no == group_no), None
        )
        if device_data is None:
            raise ValueError(f"Device with group_no {group_no} not found")

        # Unpack the payload into properties and values
        properties, values = payload

        # Use the centralized command executor with the appropriate command key
        return await self.async_set_device_property(
            "set_device_property", device_data, properties, values
        )

    async def async_set_device_property(self, command_key, *args, **kwargs) -> bool:
        """Execute a command on the HVAC device.

        This method dynamically calls a command based on the provided key,
        passing through any additional arguments and keyword arguments.
        """
        command = self.api_commands.get(command_key)
        if command is None:
            raise ValueError(f"Command '{command_key}' not found.")
        try:
            return await command(*args, **kwargs)
        except Exception as e:
            _LOGGER.error("Error executing command %s: %s", command_key, e)
            raise
        finally:
            await self.async_request_refresh()
