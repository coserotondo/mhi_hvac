"""The MHI HVAC integration."""

from dataclasses import dataclass, field
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_MODEL_ID,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_GROUPS,
    CONF_HVAC_MODE_ACTIVE,
    CONF_HVAC_MODES,
    CONF_INCLUDE_GROUPS,
    CONF_INCLUDE_INDEX,
    CONF_MAX_TEMP,
    CONF_METHOD,
    CONF_MIN_TEMP,
    CONF_PRESETS,
    CONF_SERIAL_NUMBER,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import MHIHVACDataUpdateCoordinator
from .helpers import normalize_dict
from .pymhihvac.api import (
    ApiCallFailedException,
    LoginFailedException,
    NoSessionCookieException,
)
from .pymhihvac.const import MAX_TEMP, MIN_TEMP
from .services import async_setup_services
from .utils import raise_config_entry_not_ready

_LOGGER = logging.getLogger(__name__)


@dataclass
class Config:
    """Configuration data for the MHI HVAC integration.

    This data class stores the configuration settings for the integration.
    It includes parameters for data retrieval, HVAC modes, presets, temperature limits, and update intervals.

    Args:
        method (str): The method used for retrieving data.
        include_index (str | list[str] | None, optional): The indexes to include. Defaults to None.
        include_groups (str | list[str] | None, optional): The groups to include. Defaults to None.
        presets (dict, optional): A dictionary of preset configurations. Defaults to an empty dictionary.
        hvac_modes_config (list | None, optional): A list of HVAC mode configurations. Defaults to None.
        virtual_group_config (dict, optional): A dictionary of virtual group configurations. Defaults to an empty dictionary.
        max_temp (float, optional): The maximum allowed temperature. Defaults to MAX_TEMP.
        min_temp (float, optional): The minimum allowed temperature. Defaults to MIN_TEMP.
        update_interval (timedelta, optional): The update interval. Defaults to timedelta(seconds=DEFAULT_SCAN_INTERVAL).

    """

    method: str
    include_index: list[str] | None = None
    include_groups: list[str] | None = None
    presets: dict = field(default_factory=dict)
    hvac_modes_config: list | None = None
    virtual_group_config: dict = field(default_factory=dict)
    max_temp: float = MAX_TEMP
    min_temp: float = MIN_TEMP
    update_interval: timedelta = timedelta(seconds=DEFAULT_SCAN_INTERVAL)


def _get_config(config_entry: ConfigEntry) -> Config:
    config_data = config_entry.data
    config_options = config_entry.options

    method = config_data.get(CONF_METHOD, "")
    include_index = config_data.get(CONF_INCLUDE_INDEX, None)
    include_groups = config_data.get(CONF_INCLUDE_GROUPS, None)

    presets = config_options.get(CONF_PRESETS, {})

    if hvac_modes_active := config_options.get(CONF_HVAC_MODE_ACTIVE, ""):
        hvac_modes_config = (
            config_options.get(CONF_HVAC_MODES, {})
            .get(hvac_modes_active, {})
            .get(CONF_HVAC_MODES, [])
        )
    else:
        hvac_modes_config = None

    virtual_group_config = config_options.get(CONF_GROUPS, {})
    max_temp = config_options.get(CONF_MAX_TEMP, MAX_TEMP)
    min_temp = config_options.get(CONF_MIN_TEMP, MIN_TEMP)
    update_interval = timedelta(
        seconds=config_options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )

    return Config(
        method=method,
        include_index=include_index,
        include_groups=include_groups,
        presets=presets,
        hvac_modes_config=hvac_modes_config,
        virtual_group_config=virtual_group_config,
        max_temp=max_temp,
        min_temp=min_temp,
        update_interval=update_interval,
    )


async def async_update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    """Handle options update."""
    _LOGGER.debug("Updating entry %s", config_entry.entry_id)
    coordinator: MHIHVACDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    config = _get_config(config_entry)
    coordinator.presets = config.presets
    coordinator.hvac_modes_config = config.hvac_modes_config
    coordinator.max_temp = config.max_temp
    coordinator.min_temp = config.min_temp
    old_virtual_group_config = coordinator.virtual_group_config
    if config.update_interval != coordinator.update_interval:
        coordinator.update_interval = config.update_interval
    await coordinator.async_request_refresh()  # Force data update
    # Proceed only if virtual groups changed
    if normalize_dict(config.virtual_group_config) != normalize_dict(
        old_virtual_group_config
    ):
        _LOGGER.debug(
            "Virtual groups changed for entry %s. Old: %s, New: %s",
            config_entry.entry_id,
            old_virtual_group_config,
            config.virtual_group_config,
        )
        coordinator.virtual_group_config = config.virtual_group_config
        # await coordinator.async_request_refresh()  # Force data update
        await hass.config_entries.async_reload(config_entry.entry_id)  # Reload entities

    else:
        _LOGGER.debug(
            "Virtual groups unchanged for entry %s. No reload needed",
            config_entry.entry_id,
        )


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up MHI HVAC from a config entry."""

    name = config_entry.data[CONF_NAME]
    session = async_get_clientsession(hass)
    host = config_entry.data[CONF_HOST]
    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]
    model_id = config_entry.data[CONF_MODEL_ID]
    serial_number = config_entry.data[CONF_SERIAL_NUMBER]
    config = _get_config(config_entry)
    coordinator = MHIHVACDataUpdateCoordinator(
        hass,
        logger=_LOGGER,
        name=name,
        session=session,
        host=host,
        username=username,
        password=password,
        method=config.method,
        include_index=config.include_index,
        include_groups=config.include_groups,
        model_id=model_id,
        serial_number=serial_number,
        presets=config.presets,
        hvac_modes_config=config.hvac_modes_config,
        virtual_group_config=config.virtual_group_config,
        max_temp=config.max_temp,
        min_temp=config.min_temp,
        update_interval=config.update_interval,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except (
        UpdateFailed,
        ApiCallFailedException,
        LoginFailedException,
        NoSessionCookieException,
    ) as e:
        await coordinator.async_shutdown()
        raise_config_entry_not_ready("Error initializing coordinator:", e)

    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = coordinator

    # Register services only once when the first coordinator is added.
    if len(hass.data[DOMAIN]) == 1:
        await async_setup_services(hass)

    try:
        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    except (
        UpdateFailed,
        ApiCallFailedException,
        LoginFailedException,
        NoSessionCookieException,
    ) as e:
        await coordinator.async_shutdown()
        raise_config_entry_not_ready("Error setting up platforms:", e)

    config_entry.async_on_unload(
        config_entry.add_update_listener(async_update_listener)
    )

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id, None)
    # Remove the services if no coordinators remain.
    if not hass.data[DOMAIN] and hass.services.has_service(
        DOMAIN, "set_device_property"
    ):
        hass.services.async_remove(DOMAIN, "set_device_property")
    if not hass.data[DOMAIN] and hass.services.has_service(
        DOMAIN, "set_active_hvac_modes"
    ):
        hass.services.async_remove(DOMAIN, "set_active_hvac_modes")
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Reload the config entry when options are updated."""
    await hass.config_entries.async_reload(config_entry.entry_id)
