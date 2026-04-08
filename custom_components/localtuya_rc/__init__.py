"""LocalTuyaIR Remote Control integration."""
import logging
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.REMOTE, Platform.BUTTON, Platform.CLIMATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Tuya Remote Control from a config entry."""
    _LOGGER.debug("Setting up entry")
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {}

    # Set up remote first so button/climate entities can reference it
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.REMOTE])
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.BUTTON, Platform.CLIMATE])

    # Register update listener for options flow
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    _LOGGER.debug("Unloading")
    result = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if result:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return result

async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    _LOGGER.debug("Options update for %s: %s", entry.entry_id, entry.options)
    await hass.config_entries.async_reload(entry.entry_id)
