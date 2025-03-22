"""The MHI HVAC integration."""

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_SERIAL_NUMBER,
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

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS
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


def _get_config_entry_options(
    config_entry: ConfigEntry,
) -> tuple[dict, list | None, dict, float, float, timedelta]:
    # presets
    presets = config_entry.options.get("presets", {})
    # hvac_modes_config
    if hvac_modes_active := config_entry.options.get("hvac_modes_active", ""):
        hvac_modes_config = (
            config_entry.options.get("hvac_modes", {})
            .get(hvac_modes_active, {})
            .get("hvac_modes", [])
        )
    else:
        hvac_modes_config = None
    # virtual_group_config
    virtual_group_config = config_entry.options.get("groups", {})
    # max_temp, min_temp
    max_temp = config_entry.options.get("max_temp", MAX_TEMP)
    min_temp = config_entry.options.get("min_temp", MIN_TEMP)
    # update_interval
    update_interval = timedelta(
        seconds=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    return (
        presets,
        hvac_modes_config,
        virtual_group_config,
        max_temp,
        min_temp,
        update_interval,
    )


async def async_update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    """Handle options update."""
    _LOGGER.debug("Updating entry %s", config_entry.entry_id)
    coordinator: MHIHVACDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    # get options
    (
        presets,
        hvac_modes_config,
        new_virtual_group_config,
        max_temp,
        min_temp,
        new_update_interval,
    ) = _get_config_entry_options(config_entry)
    coordinator.presets = presets
    coordinator.hvac_modes_config = hvac_modes_config
    coordinator.max_temp = max_temp
    coordinator.min_temp = min_temp
    old_virtual_group_config = coordinator.virtual_group_config
    if new_update_interval != coordinator.update_interval:
        coordinator.update_interval = new_update_interval
    await coordinator.async_request_refresh()  # Force data update
    # Proceed only if virtual groups changed
    if normalize_dict(new_virtual_group_config) != normalize_dict(
        old_virtual_group_config
    ):
        _LOGGER.debug(
            "Virtual groups changed for entry %s. Old: %s, New: %s",
            config_entry.entry_id,
            old_virtual_group_config,
            new_virtual_group_config,
        )
        coordinator.virtual_group_config = new_virtual_group_config
        # await coordinator.async_request_refresh()  # Force data update
        await hass.config_entries.async_reload(config_entry.entry_id)  # Reload entities

    else:
        _LOGGER.debug(
            "Virtual groups unchanged for entry %s. No reload needed",
            config_entry.entry_id,
        )


# async def async_setup(hass: HomeAssistant, config: dict):
#     """Set up the MHI HVAC integration."""
#     # hass.data.setdefault(DOMAIN, {})

#     # # Register services if first entry
#     # if len(hass.data[DOMAIN]) == 1:
#     #     await async_setup_services(hass)

#     return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up MHI HVAC from a config entry."""

    name = config_entry.data[CONF_NAME]
    session = async_get_clientsession(hass)
    host = config_entry.data[CONF_HOST]
    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]
    model_id = config_entry.data[CONF_MODEL_ID]
    serial_number = config_entry.data[ATTR_SERIAL_NUMBER]

    (
        presets,
        hvac_modes_config,
        virtual_group_config,
        max_temp,
        min_temp,
        update_interval,
    ) = _get_config_entry_options(config_entry)

    coordinator = MHIHVACDataUpdateCoordinator(
        hass,
        logger=_LOGGER,
        name=name,
        session=session,
        host=host,
        username=username,
        password=password,
        model_id=model_id,
        serial_number=serial_number,
        presets=presets,
        hvac_modes_config=hvac_modes_config,
        virtual_group_config=virtual_group_config,
        max_temp=max_temp,
        min_temp=min_temp,
        update_interval=update_interval,
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
