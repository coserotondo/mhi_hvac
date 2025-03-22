"""Centralized service management for MHI HVAC integration."""

import logging
from typing import TYPE_CHECKING, Any, cast

from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.entity_registry as er

from .const import DOMAIN
from .pymhihvac.api import (
    ApiCallFailedException,
    LoginFailedException,
    NoSessionCookieException,
)
from .pymhihvac.utils import InvalidTemperatureException, format_exception
from .schemas import SERVICE_SET_ACTIVE_HVAC_MODES_SCHEMA, SERVICE_SET_PROPERTIES_SCHEMA

if TYPE_CHECKING:
    # from homeassistant.config_entries import ConfigEntry

    from .coordinator import MHIHVACDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


def _build_set_properties_payload(data: dict) -> tuple[list[str], list[Any]]:
    """Build action payload using only provided fields, without any value mapping.

    This function returns a tuple of two lists: (properties, values),
    which will be passed to async_set_properties.
    The 'climate_entity' key is ignored.
    """
    # Define the set of allowed keys for the command.
    allowed_keys = {
        "onoff_mode",
        "hvac_mode",
        "target_temperature",
        "fan_mode",
        "swing_mode",
        "filter_reset",
        "lock_mode",
    }

    if payload := {
        key: value
        for key, value in data.items()
        if key in allowed_keys and value is not None
    }:
        _LOGGER.debug("Action payload: %s", payload)
        return list(payload.keys()), list(payload.values())
    raise ServiceValidationError("No valid parameters provided")


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register services when first config entry is added."""

    async def async_set_properties_handler(call: ServiceCall) -> ServiceResponse:
        """Handle set_properties service calls for one or more target climate entities.

        For our mhi_hvac integration we:
        - Process only entities whose entity_id starts with "climate.mhi_hvac_"
        - Group selected entities by config_entry.
        - For each config entry, if any selected entity is a special virtual group (is_all_devices_group True),
            use only its group_no and recalc affected real unit entities.
        - Otherwise, accumulate real unit group_nos (from real units or non-special virtual groups) without duplicates.
        - Send the command for each unique group_no.
        """
        # Ensure we have a list of entity IDs.
        entity_ids = call.data["climate_entity"]
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        # Build the payload from the service call.
        payload = _build_set_properties_payload(call.data)

        # Get our integration's climate states.
        all_climate_states = {
            state.entity_id: state
            for state in hass.states.async_all(Platform.CLIMATE)
            if state.entity_id.startswith(f"{Platform.CLIMATE}.{DOMAIN}_")
        }
        entity_registry = er.async_get(hass)

        # Group data by config_entry_id.
        # Each entry will have:
        #   - "group_nos": set of real unit group numbers
        #   - "affected_entities": set of entity_ids (initially selected)
        #   - "special": flag if a special group was encountered
        #   - "special_group_no": the special group's own group_no (if any)
        #   - "special_all_real": the set of real unit group numbers from the special virtual group
        grouped = {}  # {config_entry_id: { ... } }

        for entity_id in entity_ids:
            state = hass.states.get(entity_id)
            if not state:
                continue
            # Process only our integration's entities.
            if not entity_id.startswith("climate.mhi_hvac_"):
                continue
            group_no = state.attributes.get("group_no")
            if group_no is None:
                continue
            entity_entry = entity_registry.async_get(entity_id)
            if not entity_entry:
                continue
            config_entry_id = entity_entry.config_entry_id
            if config_entry_id not in grouped:
                grouped[config_entry_id] = {
                    "group_nos": set(),
                    "affected_entities": set(),
                    "special": False,
                    "special_group_no": None,
                    "special_all_real": set(),
                }
            # If we already have a special group for this config entry, ignore further non-special entries.
            if grouped[config_entry_id]["special"]:
                continue

            grouped[config_entry_id]["affected_entities"].add(entity_id)
            # Check if the entity is virtual.
            all_real = state.attributes.get("all_real_unit_group_nos")
            is_special = state.attributes.get("is_all_devices_group", False)
            if all_real:
                if is_special:
                    # Mark as special and store its group_no and its list of real units.
                    grouped[config_entry_id]["special"] = True
                    grouped[config_entry_id]["special_group_no"] = state.attributes.get(
                        "group_no"
                    )
                    grouped[config_entry_id]["special_all_real"] = set(all_real)
                else:
                    # For a non-special virtual group, add all real unit group_nos.
                    grouped[config_entry_id]["group_nos"].update(all_real)
                    # Also add affected entities from our integration that match these group numbers.
                    for st in all_climate_states.values():
                        candidate_group = st.attributes.get("group_no")
                        if candidate_group in all_real:
                            grouped[config_entry_id]["affected_entities"].add(
                                st.entity_id
                            )
            else:
                # It's a real unit.
                grouped[config_entry_id]["group_nos"].add(group_no)
                grouped[config_entry_id]["affected_entities"].add(entity_id)

        # Override non-special groups if a special group is present.
        for data in grouped.values():
            if data["special"]:
                # Use only the special group's group_no.
                data["group_nos"] = {data["special_group_no"]}
                # Recalculate affected entities using the special group's all_real_unit_group_nos.
                affected = set()
                for st in all_climate_states.values():
                    candidate_group = st.attributes.get("group_no")
                    if candidate_group in data["special_all_real"]:
                        affected.add(st.entity_id)
                data["affected_entities"] = affected
            # Convert sets to lists.
            data["group_nos"] = list(data["group_nos"])
            data["affected_entities"] = list(data["affected_entities"])
            # Add the common payload.
            data["payload"] = payload

        overall_result = {}
        # For each config entry, send the command for each deduplicated group.
        for config_entry_id, data in grouped.items():
            coordinator: MHIHVACDataUpdateCoordinator = hass.data[DOMAIN].get(
                config_entry_id
            )
            if coordinator is None:
                overall_result[config_entry_id] = {"error": "No coordinator found"}
                continue
            group_results = {}
            for group in data["group_nos"]:
                try:
                    if await coordinator.async_service_call_set_device_property(
                        group, payload
                    ):
                        group_results[group] = "ok"
                    else:
                        group_results[group] = "error"
                except (
                    ApiCallFailedException,
                    LoginFailedException,
                    NoSessionCookieException,
                    InvalidTemperatureException,
                    ValueError,
                ) as e:
                    group_results[group] = f"Action failed: {format_exception(e)}"
            overall_result[config_entry_id] = {
                "group_nos": data["group_nos"],
                "payload": payload,
                "affected_entities": data["affected_entities"],
                "results": group_results,
            }

        return cast(ServiceResponse, overall_result)

    async def async_set_active_hvac_modes_handler(
        service_call: ServiceCall,
    ) -> ServiceResponse:
        """Service to update config entry options."""
        # Retrieve the new option values from the service call data.

        config_entry_id = service_call.data["config_entry_id"]
        new_active_mode = service_call.data["new_active_mode"].lower()

        config_entry = hass.config_entries.async_get_entry(config_entry_id)
        if config_entry is None:
            raise ServiceValidationError(f"Config entry {config_entry_id} not found")
        config_entry_name = config_entry.title

        # valid_options = set(config_entry.options.get("hvac_modes", {}).keys())
        valid_options = {
            key.lower() for key in config_entry.options.get("hvac_modes", {})
        }
        if not valid_options:
            raise ServiceValidationError("No HVAC modes configured")

        if new_active_mode not in valid_options:
            raise ServiceValidationError(
                f"The HVAC modes '{new_active_mode}' is not configured"
            )

        current_active_mode = config_entry.options.get("hvac_modes_active", "").lower()

        if new_active_mode != current_active_mode:
            # coordinator: MHIHVACDataUpdateCoordinator = config_entry
            current_options = dict(config_entry.options)
            current_options["hvac_modes_active"] = new_active_mode.title()
            hass.config_entries.async_update_entry(
                config_entry, options=current_options
            )
            result = {config_entry_name: new_active_mode.title()}
        else:
            result = {config_entry_name: "already_configured"}

        return cast(ServiceResponse, result)

    # Register service if not already registered
    if not hass.services.has_service(DOMAIN, "set_device_property"):
        hass.services.async_register(
            DOMAIN,
            "set_device_property",
            async_set_properties_handler,
            schema=SERVICE_SET_PROPERTIES_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, "set_active_hvac_modes"):
        hass.services.async_register(
            DOMAIN,
            "set_active_hvac_modes",
            async_set_active_hvac_modes_handler,
            schema=SERVICE_SET_ACTIVE_HVAC_MODES_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
