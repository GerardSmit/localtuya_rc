"""Climate entity for AC control via Tuya IR blaster."""
import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    SWING_ON,
    SWING_OFF,
)
from homeassistant.const import (
    CONF_DEVICE_ID,
    UnitOfTemperature,
    ATTR_TEMPERATURE,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .ac_protocols import toshiba as toshiba_ac

_LOGGER = logging.getLogger(__name__)

# Map HA HVAC modes to Toshiba protocol mode strings
HVAC_TO_TOSHIBA = {
    HVACMode.AUTO: "auto",
    HVACMode.COOL: "cool",
    HVACMode.DRY: "dry",
    HVACMode.HEAT: "heat",
    HVACMode.OFF: "off",
}

# HA fan mode names → Toshiba fan strings
FAN_MODES = ["auto", "1", "2", "3", "4", "5"]

SWING_MODES = [SWING_OFF, SWING_ON]


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up climate entities from config entry options."""
    ac_devices = entry.options.get("ac_devices", [])
    dev_id = entry.data.get(CONF_DEVICE_ID)

    entities = []
    for ac_cfg in ac_devices:
        brand = ac_cfg.get("brand", "toshiba")
        name = ac_cfg.get("name", "AC")
        ac_id = ac_cfg.get("id", "ac_0")

        if brand == "toshiba":
            entities.append(
                ToshibaACClimate(hass, dev_id, ac_id, name, entry.entry_id)
            )

    if entities:
        async_add_entities(entities)


class ToshibaACClimate(ClimateEntity, RestoreEntity):
    """Climate entity that sends Toshiba AC IR commands via a Tuya remote."""

    _attr_has_entity_name = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 17
    _attr_max_temp = 30
    _attr_target_temperature_step = 1
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.AUTO,
        HVACMode.COOL,
        HVACMode.DRY,
        HVACMode.HEAT,
    ]
    _attr_fan_modes = FAN_MODES
    _attr_swing_modes = SWING_MODES
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
    )

    def __init__(self, hass, dev_id, ac_id, name, entry_id):
        self._dev_id = dev_id
        self._ac_id = ac_id
        self._entry_id = entry_id
        self._attr_unique_id = f"{dev_id}_ac_{ac_id}"
        self._attr_name = name

        # Optimistic state defaults
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = 23
        self._attr_fan_mode = "auto"
        self._attr_swing_mode = SWING_OFF
        self._swing_state = False

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self._dev_id)},
        )

    @property
    def available(self):
        """Climate entity is available only when the remote device is available."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        remote = entry_data.get("remote")
        if remote is None:
            return False
        return remote.available

    async def async_added_to_hass(self):
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None:
            return

        if last_state.state in [m.value for m in self._attr_hvac_modes]:
            self._attr_hvac_mode = HVACMode(last_state.state)

        attrs = last_state.attributes
        if "temperature" in attrs and attrs["temperature"] is not None:
            self._attr_target_temperature = int(attrs["temperature"])
        if "fan_mode" in attrs and attrs["fan_mode"] in FAN_MODES:
            self._attr_fan_mode = attrs["fan_mode"]
        if "swing_mode" in attrs:
            self._attr_swing_mode = attrs["swing_mode"]
            self._swing_state = attrs["swing_mode"] == SWING_ON

    async def _send_pulses(self, pulses: list[int]):
        """Send raw IR pulses via the remote entity."""
        registry = er.async_get(self.hass)
        remote_entity_id = registry.async_get_entity_id(
            "remote", DOMAIN, self._dev_id
        )
        if not remote_entity_id:
            raise HomeAssistantError(
                f"Remote entity not found for device {self._dev_id}"
            )

        raw_command = "raw:" + ",".join(str(p) for p in pulses)
        await self.hass.services.async_call(
            "remote",
            "send_command",
            service_data={"command": [raw_command]},
            target={"entity_id": remote_entity_id},
            blocking=True,
        )

    async def _send_state(self):
        """Encode and send the current optimistic state as an IR command."""
        if self._attr_hvac_mode == HVACMode.OFF:
            pulses = toshiba_ac.encode_off()
        else:
            mode_str = HVAC_TO_TOSHIBA.get(self._attr_hvac_mode, "auto")
            pulses = toshiba_ac.encode_command(
                temp=int(self._attr_target_temperature),
                mode=mode_str,
                fan=self._attr_fan_mode,
            )
        await self._send_pulses(pulses)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        self._attr_hvac_mode = hvac_mode
        await self._send_state()
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            self._attr_target_temperature = int(temp)
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.AUTO
        await self._send_state()
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str):
        self._attr_fan_mode = fan_mode
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.AUTO
        await self._send_state()
        self.async_write_ha_state()

    async def async_set_swing_mode(self, swing_mode: str):
        desired = swing_mode == SWING_ON
        if desired != self._swing_state:
            # Toggle swing via IR
            await self._send_pulses(toshiba_ac.encode_swing())
            self._swing_state = desired
        self._attr_swing_mode = swing_mode
        self.async_write_ha_state()
