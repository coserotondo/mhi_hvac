"""Defines the configuration flow for the MHI HVAC integration."""

import logging
import re
from typing import Any

from aiohttp import ClientError

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    ATTR_SERIAL_NUMBER,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import slugify

from .const import DEFAULT_NAME, DOMAIN
from .options_flow import OptionsFlowHandler
from .pymhihvac.api import (
    ApiCallFailedException,
    LoginFailedException,
    NoSessionCookieException,
)
from .pymhihvac.controller import MHIHVACSystemController
from .pymhihvac.utils import async_resolve_hostname, format_exception
from .schemas import (
    DATA_SCHEMA,
    HOSTNAME_PATTERN,
    IPV4_PATTERN,
    RECONFIGURE_SCHEMA,
    SERIAL_NUMBER_PATTERN,
    USERNAME_PATTERN,
)

_LOGGER = logging.getLogger(__name__)


class ConfigFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the MHI HVAC integration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle the initial step of the user configuration flow."""
        _LOGGER.debug("ConfigFlowHandler.async_step_user: %s", user_input)
        errors = {}
        if user_input is not None:
            ip_address = await async_resolve_hostname(user_input[CONF_HOST])
            _LOGGER.debug("Host IP: %s", ip_address)
            if (
                not (
                    re.match(IPV4_PATTERN, user_input[CONF_HOST])
                    or re.match(HOSTNAME_PATTERN, user_input[CONF_HOST])
                )
                or ip_address == "0.0.0.0"
            ):
                errors["base"] = "invalid_host_format"
            if not re.match(USERNAME_PATTERN, user_input[CONF_USERNAME]):
                errors["base"] = "invalid_username_format"
            if not re.match(
                SERIAL_NUMBER_PATTERN, user_input.get(ATTR_SERIAL_NUMBER, "")
            ):
                errors["base"] = "invalid_serial_number_format"

            if not errors:
                await self.async_set_unique_id(
                    slugify(f"{DOMAIN} {user_input.get(ATTR_SERIAL_NUMBER)}")
                )
                self._abort_if_unique_id_configured()
                try:
                    api_controller = MHIHVACSystemController(
                        user_input[CONF_HOST],
                        user_input[CONF_USERNAME],
                        user_input[CONF_PASSWORD],
                        async_get_clientsession(self.hass),
                    )
                    session_cookie = await api_controller.async_login()
                    _LOGGER.debug(
                        "Test connection successful, session cookie: %s", session_cookie
                    )
                except (
                    ClientError,
                    TimeoutError,
                    ApiCallFailedException,
                    LoginFailedException,
                    NoSessionCookieException,
                ) as e:
                    _LOGGER.error("Error during login: %s", format_exception(e))
                    errors["base"] = "invalid_auth"

            if not errors:
                return self.async_create_entry(title=DEFAULT_NAME, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle re-configure flow to update host, username, and password."""
        errors = {}
        if user_input is not None:
            ip_address = await async_resolve_hostname(user_input[CONF_HOST])
            _LOGGER.debug("Reauth: Host IP: %s", ip_address)
            if (
                not (
                    re.match(IPV4_PATTERN, user_input[CONF_HOST])
                    or re.match(HOSTNAME_PATTERN, user_input[CONF_HOST])
                )
                or ip_address == "0.0.0.0"
            ):
                errors["base"] = "invalid_host_format"
            if not re.match(USERNAME_PATTERN, user_input[CONF_USERNAME]):
                errors["base"] = "invalid_username_format"
            if not errors:
                try:
                    api_controller = MHIHVACSystemController(
                        user_input[CONF_HOST],
                        user_input[CONF_USERNAME],
                        user_input[CONF_PASSWORD],
                        async_get_clientsession(self.hass),
                    )
                    session_cookie = await api_controller.async_login()
                    _LOGGER.debug(
                        "Reauth: Test connection successful, session cookie: %s",
                        session_cookie,
                    )
                except (
                    ClientError,
                    TimeoutError,
                    ApiCallFailedException,
                    LoginFailedException,
                    NoSessionCookieException,
                ) as e:
                    _LOGGER.error("Reauth error during login: %s", format_exception(e))
                    errors["base"] = "invalid_auth"

            if not errors:
                data_updates = {
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data_updates=data_updates,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=RECONFIGURE_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowHandler:
        """Return the options flow."""
        _LOGGER.debug("ConfigFlowHandler.async_get_options_flow: %s", config_entry)
        return OptionsFlowHandler(config_entry)
