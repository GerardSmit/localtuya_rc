"""Button entities for learned IR/RF commands."""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers import entity_registry as er
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    CODE_STORAGE_VERSION,
    CODE_STORAGE_CODES,
    SIGNAL_COMMANDS_UPDATED,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up button entities from learned commands."""
    dev_id = entry.data.get(CONF_DEVICE_ID)

    storage = Store(hass, CODE_STORAGE_VERSION, f"{CODE_STORAGE_CODES}_{dev_id}")
    codes = await storage.async_load() or {}

    tracked_buttons = {}

    def _create_entities_from_codes(current_codes):
        """Create button entities for any new commands."""
        entities = []
        for device_name, commands in current_codes.items():
            for command_name, code in commands.items():
                uid = f"{dev_id}_btn_{device_name}_{command_name}"
                if uid not in tracked_buttons:
                    entity = TuyaRCButton(dev_id, device_name, command_name, code, entry.entry_id)
                    entities.append(entity)
                    tracked_buttons[uid] = entity
        return entities

    initial = _create_entities_from_codes(codes)
    if initial:
        async_add_entities(initial)

    async def _handle_commands_updated():
        """Handle updated commands — add new buttons, remove deleted ones."""
        updated_codes = await storage.async_load() or {}

        # Add new button entities
        new_entities = _create_entities_from_codes(updated_codes)
        if new_entities:
            async_add_entities(new_entities)

        # Remove deleted button entities
        current_uids = set()
        for device_name, commands in updated_codes.items():
            for command_name in commands:
                current_uids.add(f"{dev_id}_btn_{device_name}_{command_name}")

        registry = er.async_get(hass)
        for uid in list(tracked_buttons.keys()):
            if uid not in current_uids:
                entity_id = registry.async_get_entity_id("button", DOMAIN, uid)
                if entity_id:
                    registry.async_remove(entity_id)
                del tracked_buttons[uid]

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, f"{SIGNAL_COMMANDS_UPDATED}_{dev_id}", _handle_commands_updated
        )
    )


class TuyaRCButton(ButtonEntity):
    """Button entity for a learned IR/RF command."""

    _attr_should_poll = True

    def __init__(self, dev_id, device_name, command_name, code, entry_id):
        self._dev_id = dev_id
        self._device_name = device_name
        self._command_name = command_name
        self._code = code
        self._entry_id = entry_id
        self._attr_unique_id = f"{dev_id}_btn_{device_name}_{command_name}"
        self._attr_name = f"{device_name} {command_name}"
        self._attr_icon = "mdi:remote"

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self._dev_id)},
        )

    @property
    def available(self):
        """Button is available only when the remote is on and reachable."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        remote = entry_data.get("remote")
        if remote is None:
            return False
        return remote.is_on and remote.available

    async def async_press(self):
        """Send the learned command."""
        registry = er.async_get(self.hass)
        remote_entity_id = registry.async_get_entity_id("remote", DOMAIN, self._dev_id)

        if not remote_entity_id:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="remote_entity_not_found",
                translation_placeholders={"device_id": self._dev_id},
            )

        await self.hass.services.async_call(
            "remote",
            "send_command",
            service_data={
                "device": self._device_name,
                "command": [self._command_name],
            },
            target={"entity_id": remote_entity_id},
            blocking=True,
        )
