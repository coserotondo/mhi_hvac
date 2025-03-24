"""Defines constants used in the MHI HVAC custom component."""

from pymhihvac.const import MHIHVACMode

from homeassistant.components.climate import HVACMode
from homeassistant.const import ATTR_SERIAL_NUMBER, Platform, UnitOfTemperature

DOMAIN = "mhi_hvac"
PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SENSOR,
]

ENTITY_SUFFIXES = {
    "MHIHVACClimateEntity": {
        "unique_id": f"{Platform.CLIMATE}",
        "friendly_name": "",
    },
    "MHIHVACRoomTempSensorEntity": {
        "unique_id": f"room_temperature_{Platform.SENSOR}",
        "friendly_name": "Room Temperature",
    },
    "MHIHVACFilterSensorEntity": {
        "unique_id": f"filter_sign_{Platform.BINARY_SENSOR}",
        "friendly_name": "Filter",
    },
    "MHIHVACRCLockSensorEntity": {
        "unique_id": f"rc_lock_{Platform.BINARY_SENSOR}",
        "friendly_name": "Remote Control",
    },
}


DEFAULT_MANUFACTURER = "Mitsubishi Heavy Industries"
DEFAULT_NAME = "MHI HVAC"
DEFAULT_MODEL = "MULTI-SYSTEM AIR-CONDITIONER"
ALL_GROUPS = "All Groups"

DEFAULT_SCAN_INTERVAL = 30

TEMPERATURE_UNIT = UnitOfTemperature.CELSIUS
CONF_SERIAL_NUMBER = ATTR_SERIAL_NUMBER
CONF_METHOD = "method"
CONF_INCLUDE_INDEX = "include_index"
CONF_INCLUDE_GROUPS = "include_groups"
CONF_PRESETS = "presets"
CONF_HVAC_MODE_ACTIVE = "hvac_modes_active"
CONF_HVAC_MODES = "hvac_modes"
CONF_GROUPS = "groups"
CONF_MAX_TEMP = "max_temp"
CONF_MIN_TEMP = "min_temp"

# DEFAULT_VIRTUAL_GROUPS = {
#     "129": {
#         "name": "All Units",
#         "units": "all",
#         "all_groups": True,
#     },  # Use "all" keyword
#     "130": {
#         "name": "Camere Letto",
#         "units": ["2", "4", "6"],
#     },
# }

# DEFAULT_VIRTUAL_GROUPS = {
#     "130": {
#         "name": "Camere Letto",
#         "units": ["2", "4", "6"],
#     },
# }
MIN_GROUP_NO = 1
MAX_GROUP_NO = 128
ALL_UNITS_GROUP_NO = 129
NUM_CONFIGURED_GROUPS = 6

MHI_HVAC_MODES = [
    mode for mode in HVACMode if mode.value in {m.value for m in MHIHVACMode}
]
