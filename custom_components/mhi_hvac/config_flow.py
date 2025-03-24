"""Defines the configuration flow for the MHI HVAC integration."""

import logging
import re
from typing import Any

from aiohttp import ClientError
from pymhihvac.api import (
    ApiCallFailedException,
    LoginFailedException,
    NoSessionCookieException,
)
from pymhihvac.controller import MHIHVACSystemController
from pymhihvac.utils import async_resolve_hostname, format_exception

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import slugify

from .const import (
    CONF_INCLUDE_GROUPS,
    CONF_INCLUDE_INDEX,
    CONF_METHOD,
    CONF_SERIAL_NUMBER,
    DEFAULT_NAME,
    DOMAIN,
)
from .options_flow import OptionsFlowHandler
from .schemas import (
    BLOCKS_LIST_PATTERN,
    DATA_SCHEMA,
    HOSTNAME_PATTERN,
    IPV4_PATTERN,
    SERIAL_NUMBER_PATTERN,
    UNITS_LIST_PATTERN,
    USERNAME_PATTERN,
    reconfigure_schema,
)
from .utils import split_if_string

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
                SERIAL_NUMBER_PATTERN, user_input.get(CONF_SERIAL_NUMBER, "")
            ):
                errors["base"] = "invalid_serial_number_format"
            if include_index := user_input.get(CONF_INCLUDE_INDEX, ""):
                if not re.match(BLOCKS_LIST_PATTERN, include_index):
                    errors["base"] = "invalid_blocks_format"
                else:
                    user_input[CONF_INCLUDE_INDEX] = split_if_string(include_index)
            if include_groups := user_input.get(CONF_INCLUDE_GROUPS, ""):
                if not re.match(UNITS_LIST_PATTERN, CONF_INCLUDE_GROUPS):
                    errors["base"] = "invalid_units_format"
                else:
                    user_input[CONF_INCLUDE_GROUPS] = split_if_string(include_groups)
            if not errors:
                await self.async_set_unique_id(
                    slugify(f"{DOMAIN} {user_input.get(CONF_SERIAL_NUMBER)}")
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
        """Handle re-configure flow.

        Update host, username, password, method, included_index and included_groups.
        """
        errors = {}
        current_data = self._get_reconfigure_entry().data
        current_values = {
            CONF_HOST: current_data.get(CONF_HOST, ""),
            CONF_USERNAME: current_data.get(CONF_USERNAME, ""),
            CONF_PASSWORD: current_data.get(CONF_PASSWORD, ""),
            CONF_METHOD: current_data.get(CONF_METHOD, ""),
            CONF_INCLUDE_INDEX: current_data.get(CONF_INCLUDE_INDEX, ""),
            CONF_INCLUDE_GROUPS: current_data.get(CONF_INCLUDE_GROUPS, ""),
        }
        if user_input is not None:
            ip_address = await async_resolve_hostname(user_input[CONF_HOST])
            _LOGGER.debug("Reauth: Host IP: %s", ip_address)
            if (
                not re.match(IPV4_PATTERN, user_input[CONF_HOST])
                and not re.match(HOSTNAME_PATTERN, user_input[CONF_HOST])
            ) or ip_address == "0.0.0.0":
                errors["base"] = "invalid_host_format"
            if not re.match(USERNAME_PATTERN, user_input[CONF_USERNAME]):
                errors["base"] = "invalid_username_format"
            if include_index := user_input.get(CONF_INCLUDE_INDEX, ""):
                if not re.match(BLOCKS_LIST_PATTERN, include_index):
                    errors["base"] = "invalid_blocks_format"
                else:
                    user_input[CONF_INCLUDE_INDEX] = split_if_string(include_index)
            if include_groups := user_input.get(CONF_INCLUDE_GROUPS, ""):
                if not re.match(UNITS_LIST_PATTERN, include_groups):
                    errors["base"] = "invalid_units_format"
                else:
                    user_input[CONF_INCLUDE_GROUPS] = split_if_string(include_groups)
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
                    CONF_METHOD: user_input[CONF_METHOD],
                    CONF_INCLUDE_INDEX: user_input.get(CONF_INCLUDE_INDEX, ""),
                    CONF_INCLUDE_GROUPS: user_input.get(CONF_INCLUDE_GROUPS, ""),
                }
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data_updates=data_updates,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=reconfigure_schema(current_values),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowHandler:
        """Return the options flow."""
        _LOGGER.debug("ConfigFlowHandler.async_get_options_flow: %s", config_entry)
        return OptionsFlowHandler(config_entry)
