"""Climate entity for AC control via Tuya IR blaster."""
import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    SWING_ON,
    SWING_OFF,
    PRESET_NONE,
    PRESET_BOOST,
    PRESET_ECO,
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
from .ac_protocols import get_protocol

_LOGGER = logging.getLogger(__name__)

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

        protocol = get_protocol(brand)
        if protocol is None:
            _LOGGER.warning("Unknown AC brand '%s', skipping", brand)
            continue

        entities.append(
            ACClimate(hass, dev_id, ac_id, name, entry.entry_id, protocol)
        )

    if entities:
        async_add_entities(entities)


class ACClimate(ClimateEntity, RestoreEntity):
    """Climate entity that sends AC IR commands via a Tuya remote."""

    _attr_has_entity_name = False
    _attr_should_poll = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1

    def __init__(self, hass, dev_id, ac_id, name, entry_id, protocol):
        self._dev_id = dev_id
        self._ac_id = ac_id
        self._entry_id = entry_id
        self._protocol = protocol
        self._attr_unique_id = f"{dev_id}_ac_{ac_id}"
        self._attr_name = name

        # Configure from protocol
        self._attr_min_temp = protocol.min_temp
        self._attr_max_temp = protocol.max_temp
        self._attr_hvac_modes = protocol.hvac_modes
        self._attr_fan_modes = protocol.fan_modes

        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if protocol.has_swing:
            features |= ClimateEntityFeature.SWING_MODE
            self._attr_swing_modes = SWING_MODES
        if protocol.preset_modes:
            features |= ClimateEntityFeature.PRESET_MODE
            self._attr_preset_modes = [PRESET_NONE] + protocol.preset_modes
        self._attr_supported_features = features

        # Optimistic state defaults
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = 23
        self._attr_fan_mode = protocol.fan_modes[0] if protocol.fan_modes else "auto"
        self._attr_swing_mode = SWING_OFF
        self._attr_preset_mode = PRESET_NONE
        self._last_active_mode = HVACMode.AUTO

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self._dev_id)},
        )

    @property
    def available(self):
        """Climate entity is available only when the remote is on and reachable."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        remote = entry_data.get("remote")
        if remote is None:
            return False
        return remote.is_on and remote.available

    async def async_added_to_hass(self):
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None:
            # Write state immediately so the entity is available right after setup
            self.async_write_ha_state()
            return

        if last_state.state in [m.value for m in self._attr_hvac_modes]:
            self._attr_hvac_mode = HVACMode(last_state.state)
            if self._attr_hvac_mode != HVACMode.OFF:
                self._last_active_mode = self._attr_hvac_mode

        attrs = last_state.attributes
        if "temperature" in attrs and attrs["temperature"] is not None:
            self._attr_target_temperature = int(attrs["temperature"])
        if "fan_mode" in attrs and attrs["fan_mode"] in self._attr_fan_modes:
            self._attr_fan_mode = attrs["fan_mode"]
        if "swing_mode" in attrs:
            self._attr_swing_mode = attrs["swing_mode"]
        if "preset_mode" in attrs and hasattr(self, "_attr_preset_modes"):
            if attrs["preset_mode"] in self._attr_preset_modes:
                self._attr_preset_mode = attrs["preset_mode"]

        # Write state immediately so the entity is available right after setup
        self.async_write_ha_state()

    async def _send_pulses(self, pulses: list[int]):
        """Send raw IR pulses via the remote entity."""
        registry = er.async_get(self.hass)
        remote_entity_id = registry.async_get_entity_id(
            "remote", DOMAIN, self._dev_id
        )
        if not remote_entity_id:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="remote_entity_not_found",
                translation_placeholders={"device_id": self._dev_id},
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
        preset = None
        if hasattr(self, "_attr_preset_mode") and self._attr_preset_mode != PRESET_NONE:
            preset = self._attr_preset_mode
        pulses = self._protocol.encode_state(
            mode=self._attr_hvac_mode,
            temp=int(self._attr_target_temperature),
            fan=self._attr_fan_mode,
            preset=preset,
        )
        await self._send_pulses(pulses)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        prev_mode = self._attr_hvac_mode
        self._attr_hvac_mode = hvac_mode
        try:
            await self._send_state()
        except Exception:
            self._attr_hvac_mode = prev_mode
            raise
        if hvac_mode != HVACMode.OFF:
            self._last_active_mode = hvac_mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get(ATTR_TEMPERATURE)
        prev_temp = self._attr_target_temperature
        prev_mode = self._attr_hvac_mode
        if temp is not None:
            self._attr_target_temperature = int(temp)
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.AUTO
        try:
            await self._send_state()
        except Exception:
            self._attr_target_temperature = prev_temp
            self._attr_hvac_mode = prev_mode
            raise
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str):
        prev_fan = self._attr_fan_mode
        prev_mode = self._attr_hvac_mode
        self._attr_fan_mode = fan_mode
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.AUTO
        try:
            await self._send_state()
        except Exception:
            self._attr_fan_mode = prev_fan
            self._attr_hvac_mode = prev_mode
            raise
        self.async_write_ha_state()

    async def async_set_swing_mode(self, swing_mode: str):
        await self._send_pulses(self._protocol.encode_swing(swing_mode == SWING_ON))
        self._attr_swing_mode = swing_mode
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str):
        prev_preset = self._attr_preset_mode
        prev_mode = self._attr_hvac_mode
        self._attr_preset_mode = preset_mode
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.AUTO
        try:
            await self._send_state()
        except Exception:
            self._attr_preset_mode = prev_preset
            self._attr_hvac_mode = prev_mode
            raise
        self.async_write_ha_state()

    async def async_turn_on(self):
        """Turn on using the last active HVAC mode."""
        await self.async_set_hvac_mode(self._last_active_mode)

    async def async_turn_off(self):
        """Turn off the AC."""
        await self.async_set_hvac_mode(HVACMode.OFF)
