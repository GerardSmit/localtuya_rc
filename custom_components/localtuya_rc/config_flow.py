"""Config flow for the LocalTuyaIR Remote Control integration."""

import logging
import voluptuous as vol
import tinytuya
from tinytuya import Contrib, Cloud

from .const import *

from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_DEVICE_ID,
    CONF_REGION,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.exceptions import HomeAssistantError

from .rc_encoder import rc_auto_decode

_LOGGER = logging.getLogger(__name__)

class LocalTuyaIRConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for LocalTuyaIR Remote Control."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        # Default config
        self.config = {
            CONF_NAME: DEFAULT_FRIENDLY_NAME,
            CONF_DEVICE_ID: '',
            CONF_LOCAL_KEY: '',
            CONF_PROTOCOL_VERSION: 'Auto',
            CONF_PERSISTENT_CONNECTION: DEFAULT_PERSISTENT_CONNECTION,
            CONF_REGION: 'eu',
            CONF_CLIENT_ID: '',
            CONF_CLIENT_SECRET: '',
            CONF_HOST: '',
        }
        self.cloud = False
        self.cloud_info = None

    @staticmethod
    @callback
    def async_get_options_flow(entry):
        return LocalTuyaIROptionsFlow(entry)

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        return await self.async_step_method()

    async def async_step_method(self, user_input=None):
        """Select: use Tuya Cloud API or enter local key manually."""
        # Ask user to to obtain the local key: via the API or enter manually
        return self.async_show_menu(
            step_id="method",
            menu_options=["cloud", "ip_method"])

    def _get_cloud_devices(self, region, client_id, client_secret):
        cloud = Cloud(region, client_id, client_secret)
        status = cloud.getconnectstatus()
        return cloud, status

    async def async_step_cloud(self, user_input=None):
        """Handle the API step, enter credentials."""
        errors = {}
        if user_input is not None:
            try:
                self.config[CONF_REGION] = user_input[CONF_REGION]
                self.config[CONF_CLIENT_ID] = user_input[CONF_CLIENT_ID]
                self.config[CONF_CLIENT_SECRET] = user_input[CONF_CLIENT_SECRET]
                cloud, status = await self.hass.async_add_executor_job(self._get_cloud_devices, user_input[CONF_REGION], user_input[CONF_CLIENT_ID], user_input[CONF_CLIENT_SECRET])
                if not status:
                    errors["base"] = "cloud_error"
                elif 'Err' in status and status['Err'] == '911':
                    errors["base"] = "cloud_unauthorized"
                else:
                    devices = await self.hass.async_add_executor_job(cloud.getdevices)
                    if not devices:
                        errors["base"] = "cloud_no_devices"
                    else:
                        self.cloud_devices = devices
                        self.cloud = True
                        return await self.async_step_ip_method()
            except Exception as e:
                _LOGGER.error("Cloud API error: %s", e, exc_info=True)
                errors["base"] = "unknown"
        schema = vol.Schema(
            {
                vol.Required(CONF_REGION, default=self.config[CONF_REGION]): vol.In(["us", "us-e", "eu", "eu-w", "in", "cn", "sg"]),
                vol.Required(CONF_CLIENT_ID, default=self.config[CONF_CLIENT_ID]): cv.string,
                vol.Required(CONF_CLIENT_SECRET, default=self.config[CONF_CLIENT_SECRET]): cv.string
            }
        )
        return self.async_show_form(
            step_id="cloud",
            errors=errors,
            data_schema=schema
        )

    async def async_step_ip_method(self, user_input=None, errors={}):
        """Ask user to scan for devices or enter the IP manually."""
        if self.cloud:
            return self.async_show_menu(
                step_id="ip_method",
                menu_options=["pre_scan", "ask_ip"])
        else:
            return self.async_show_menu(
                step_id="ip_method",
                menu_options=["pre_scan", "config"])
        
    async def async_step_ask_ip(self, user_input=None, errors={}):
        """Ask user to enter the IP manually."""
        if user_input is not None:
            self.config[CONF_HOST] = user_input[CONF_HOST]
            id = user_input[CONF_DEVICE_ID].split(' ')[-1][1:-1]
            self.config[CONF_DEVICE_ID] = id
            devices = [device for device in self.cloud_devices if device['id'] == id]
            if not devices:
                return await self.async_step_ask_ip(errors={"base": "unknown"})
            self.cloud_info = devices[0]
            self.config[CONF_NAME] = devices[0]['name']
            self.config[CONF_LOCAL_KEY] = devices[0]['key']
            return await self.async_step_config()
        device_list = [f"{device['name']} ({device['id']})" for device in self.cloud_devices]
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=self.config[CONF_HOST]): cv.string,
                vol.Required(CONF_DEVICE_ID): vol.In(device_list),
            }
        )
        return self.async_show_form(
            step_id="ask_ip",
            errors=errors,
            data_schema=schema
        )

    async def async_step_pre_scan(self, user_input=None, errors={}):
        """Just show a message to the user."""
        if user_input is not None:
            return await self.async_step_scan()
        return self.async_show_form(
            step_id="pre_scan",
            errors=errors,
            data_schema=vol.Schema({})
        )

    async def async_step_scan(self, user_input=None):
        """Scan local network for devices."""
        errors = {}
        if user_input is not None:
            spl = user_input[CONF_HOST].split(' ', maxsplit=1)
            ip = spl[0]
            self.config[CONF_HOST] = ip
            self.config[CONF_DEVICE_ID] = self.scan_devices[ip]["gwId"]
            if self.cloud:
                for device in self.cloud_devices:
                    if device['id'] == self.config[CONF_DEVICE_ID]:
                        self.cloud_info = device
                        self.config[CONF_NAME] = device['name']
                        self.config[CONF_LOCAL_KEY] = device['key']
                        break
            return await self.async_step_config()
        try:
            self.scan_devices = await self.hass.async_add_executor_job(tinytuya.deviceScan)
            for ip in self.scan_devices:
                device = self.scan_devices[ip]
                _LOGGER.debug("Device found: %s", device)
            if len(self.scan_devices) == 0:
                return await self.async_step_pre_scan(errors={"base": "tuya_not_found"})
            if not self.cloud:
                ip_list = [f"{ip} ({self.scan_devices[ip]['gwId']})" for ip in self.scan_devices]
            else:
                ip_list = []
                for ip in self.scan_devices:
                    for device in self.cloud_devices:
                        if device['id'] == self.scan_devices[ip]["gwId"]:
                            ip_list.append(f"{ip} - {device['name']}")
                            break
                if len(ip_list) == 0:
                    return await self.async_step_pre_scan(errors={"base": "tuya_not_found"})
            schema = vol.Schema(
            {
                vol.Required(CONF_HOST): vol.In(ip_list)
            })
        except Exception as e:
            _LOGGER.error("Scan error: %s", e, exc_info=True)
            return self.async_abort(reason='unknown')
        return self.async_show_form(
            step_id="scan",
            errors=errors,
            data_schema=schema
        )

    def _test_connection(self, dev_id, address, local_key, version):
        _LOGGER.debug("Testing connection to %s at %s with key %s", dev_id, address, local_key)
        device = Contrib.IRRemoteControlDevice(dev_id=dev_id, address=address, local_key=local_key, version=version, connection_timeout=5, connection_retry_delay=0.5, connection_retry_limit=2)
        try:
            status = device.status()
            _LOGGER.debug("Connection test status: %s, control type detected: %s", status, device.control_type)
            return device, status
        except Exception:
            device.close()
            raise

    async def async_step_config(self, user_input=None, errors={}):
        """Last config step"""
        if user_input is not None:
            self.config[CONF_NAME] = user_input[CONF_NAME]
            self.config[CONF_HOST] = user_input[CONF_HOST]
            self.config[CONF_DEVICE_ID] = user_input[CONF_DEVICE_ID]
            self.config[CONF_LOCAL_KEY] = user_input[CONF_LOCAL_KEY]
            self.config[CONF_PERSISTENT_CONNECTION] = user_input[CONF_PERSISTENT_CONNECTION]
            self.config[CONF_PROTOCOL_VERSION] = user_input[CONF_PROTOCOL_VERSION]
            # Bruteforce the protocol version (in order of preference)
            try_versions = TUYA_VERSIONS if user_input[CONF_PROTOCOL_VERSION] == "Auto" else [user_input[CONF_PROTOCOL_VERSION]]
            version_ok = None
            device = None
            for version in try_versions:
                _LOGGER.debug("Trying protocol version %s", version)
                try:
                    test_device, status = await self.hass.async_add_executor_job(self._test_connection, user_input[CONF_DEVICE_ID], user_input[CONF_HOST], user_input[CONF_LOCAL_KEY], version)
                except Exception as e:
                    _LOGGER.error("Device test error, exception %s: %s", type(e), e, exc_info=True)
                    continue
                if "Error" not in status:
                    # Close previously tested device if any
                    if device:
                        device.close()
                    device = test_device
                    version_ok = version
                    break
                else:
                    test_device.close()
            if not version_ok:
                errors["base"] = "cannot_connect"
                _LOGGER.error(f"Cannot connect to device using any protocol version")
            elif not device.control_type:
                errors["base"] = "no_control_type"
                _LOGGER.error(f"Device test error: control type not detected")
                device.close()
            elif self.config[CONF_DEVICE_ID] in self._async_current_ids():
                device.close()
                return self.async_abort(reason="already_configured")
            else:
                device.close()
                # Ok!
                self.config[CONF_PROTOCOL_VERSION] = version_ok
                if self.cloud and 'key' in self.cloud_info:
                    del self.cloud_info['key'] # to protect the key
                self.config[CONF_CLOUD_INFO] = self.cloud_info if self.cloud else None
                _LOGGER.debug("Config: %s", self.config)
                await self.async_set_unique_id(self.config[CONF_DEVICE_ID])
                return self.async_create_entry(title=self.config[CONF_NAME], data=self.config)
        versions_sorted = TUYA_VERSIONS.copy()
        versions_sorted.sort()
        schema = vol.Schema({
            vol.Required(CONF_NAME, default=self.config[CONF_NAME]): cv.string,
            vol.Required(CONF_HOST, default=self.config[CONF_HOST]): cv.string,
            vol.Required(CONF_DEVICE_ID, default=self.config[CONF_DEVICE_ID]): cv.string,
            vol.Required(CONF_LOCAL_KEY, default=self.config[CONF_LOCAL_KEY]): cv.string,
            vol.Required(CONF_PROTOCOL_VERSION, default=self.config[CONF_PROTOCOL_VERSION]): vol.In(["Auto"] + versions_sorted),
            vol.Required(CONF_PERSISTENT_CONNECTION, default=self.config[CONF_PERSISTENT_CONNECTION]): cv.boolean
        })
        return self.async_show_form(
            step_id="config",
            errors=errors,
            data_schema=schema
        )


class LocalTuyaIROptionsFlow(config_entries.OptionsFlow):
    """Options flow for LocalTuyaIR Remote Control."""
    
    def __init__(self, entry):
        """Initialize the options flow."""
        self.entry = entry
        self.config = dict(entry.data.items())
        self._learn_device = None
        self._learn_command = None
        self._learn_type = None
        _LOGGER.debug("Options flow init, current config: %s", self.config)

    async def async_step_init(self, user_input=None):
        """Show main menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["learn_command", "manage_commands", "add_ac", "settings"],
        )

    # ── Learn Command ──────────────────────────────────────────────

    async def async_step_learn_command(self, user_input=None):
        """Step 1: Enter device name, command name, and type."""
        errors = {}
        if user_input is not None:
            self._learn_device = user_input.get("device", "").strip()
            self._learn_command = user_input.get("command", "").strip()
            self._learn_type = user_input.get("command_type", "ir")
            if not self._learn_device:
                errors["device"] = "required"
            elif not self._learn_command:
                errors["command"] = "required"
            else:
                return await self.async_step_learn_wait()

        schema = vol.Schema({
            vol.Required("device", default=self._learn_device or ""): cv.string,
            vol.Required("command", default=self._learn_command or ""): cv.string,
            vol.Required("command_type", default="ir"): vol.In({"ir": "IR (infrared)", "rf": "RF (radio)"}),
        })
        return self.async_show_form(
            step_id="learn_command",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_learn_wait(self, user_input=None):
        """Step 2: Instruct user to press the button, then do the learning."""
        if user_input is not None:
            return await self._async_do_learn()

        return self.async_show_form(
            step_id="learn_wait",
            data_schema=vol.Schema({}),
            description_placeholders={
                "device": self._learn_device,
                "command": self._learn_command,
                "type": self._learn_type.upper(),
            },
        )

    async def _async_do_learn(self):
        """Execute the learning process via the remote entity."""
        dev_id = self.entry.data.get(CONF_DEVICE_ID)
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        remote = entry_data.get("remote")

        if remote is None or not remote.available:
            return self.async_show_form(
                step_id="learn_done",
                data_schema=vol.Schema({}),
                errors={"base": "device_not_ready"},
                description_placeholders={"result": ""},
            )

        try:
            if self._learn_type == "rf":
                button = await self.hass.async_add_executor_job(
                    remote._receive_button_rf
                )
            else:
                button = await self.hass.async_add_executor_job(
                    remote._receive_button
                )

            if isinstance(button, str) and button.startswith("ERROR"):
                raise Exception(button)
            if not button:
                raise TimeoutError("No signal received")

            # Decode
            if self._learn_type == "ir":
                pulses = Contrib.IRRemoteControlDevice.base64_to_pulses(button)
                decoded = rc_auto_decode(pulses)
            else:
                decoded = "rf:" + button

            # Save to storage
            storage = Store(self.hass, CODE_STORAGE_VERSION, CODE_STORAGE_CODES)
            codes = await storage.async_load() or {}
            codes.setdefault(self._learn_device, {})[self._learn_command] = decoded
            await storage.async_save(codes)

            # Update remote entity's in-memory codes and notify button platform
            remote._codes = codes
            remote.schedule_update_ha_state()
            async_dispatcher_send(
                self.hass, f"{SIGNAL_COMMANDS_UPDATED}_{dev_id}"
            )

            return self.async_show_form(
                step_id="learn_done",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "result": f"✅ Learned **{self._learn_command}** for **{self._learn_device}**\n\nCode: `{decoded}`",
                },
            )
        except TimeoutError:
            return self.async_show_form(
                step_id="learn_done",
                data_schema=vol.Schema({}),
                errors={"base": "learn_timeout"},
                description_placeholders={"result": ""},
            )
        except Exception as e:
            _LOGGER.error("Learn error: %s", e, exc_info=True)
            return self.async_show_form(
                step_id="learn_done",
                data_schema=vol.Schema({}),
                errors={"base": "learn_error"},
                description_placeholders={"result": ""},
            )

    async def async_step_learn_done(self, user_input=None):
        """Show result and return to menu."""
        return await self.async_step_init()

    # ── Manage Commands ────────────────────────────────────────────

    async def async_step_manage_commands(self, user_input=None):
        """List learned commands and allow deletion."""
        storage = Store(self.hass, CODE_STORAGE_VERSION, CODE_STORAGE_CODES)
        codes = await storage.async_load() or {}

        # Build flat list of "device: command" entries
        command_list = {}
        for device_name, commands in codes.items():
            for command_name in commands:
                key = f"{device_name}: {command_name}"
                command_list[key] = key

        if not command_list:
            return await self.async_step_manage_commands_empty()

        if user_input is not None:
            selected = user_input.get("command_to_delete")
            if selected and ": " in selected:
                dev, cmd = selected.split(": ", 1)
                if dev in codes and cmd in codes[dev]:
                    del codes[dev][cmd]
                    if not codes[dev]:
                        del codes[dev]
                    await storage.async_save(codes)

                    # Update remote entity
                    dev_id = self.entry.data.get(CONF_DEVICE_ID)
                    entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
                    remote = entry_data.get("remote")
                    if remote:
                        remote._codes = codes
                        remote.schedule_update_ha_state()
                    async_dispatcher_send(
                        self.hass,
                        f"{SIGNAL_COMMANDS_UPDATED}_{dev_id}",
                    )
            return await self.async_step_init()

        schema = vol.Schema({
            vol.Required("command_to_delete"): vol.In(command_list),
        })
        return self.async_show_form(
            step_id="manage_commands",
            data_schema=schema,
        )

    async def async_step_manage_commands_empty(self, user_input=None):
        """No commands to manage."""
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(
            step_id="manage_commands_empty",
            data_schema=vol.Schema({}),
        )

    # ── AC Controllers ─────────────────────────────────────────────

    async def async_step_add_ac(self, user_input=None):
        """Add a preconfigured AC controller."""
        errors = {}
        if user_input is not None:
            ac_name = user_input.get("ac_name", "").strip()
            ac_brand = user_input.get("ac_brand", "toshiba")
            if not ac_name:
                errors["ac_name"] = "required"
            else:
                # Generate a unique id
                options = dict(self.entry.options)
                ac_devices = list(options.get("ac_devices", []))
                existing_ids = [d.get("id", "") for d in ac_devices]
                ac_id = f"ac_{len(ac_devices)}"
                while ac_id in existing_ids:
                    ac_id = f"ac_{int(ac_id.split('_')[1]) + 1}"

                ac_devices.append({
                    "id": ac_id,
                    "brand": ac_brand,
                    "name": ac_name,
                })
                options["ac_devices"] = ac_devices
                self.hass.config_entries.async_update_entry(
                    self.entry, options=options
                )
                # Reload to create the climate entity
                return self.async_create_entry(data={})

        schema = vol.Schema({
            vol.Required("ac_name", default=""): cv.string,
            vol.Required("ac_brand", default="toshiba"): vol.In({
                "toshiba": "Toshiba",
            }),
        })
        return self.async_show_form(
            step_id="add_ac",
            data_schema=schema,
            errors=errors,
        )

    # ── Settings ───────────────────────────────────────────────────

    async def async_step_settings(self, user_input=None):
        """Manage device settings (persistent connection toggle)."""
        if user_input is not None:
            self.config[CONF_PERSISTENT_CONNECTION] = user_input[CONF_PERSISTENT_CONNECTION]
            _LOGGER.debug("Config updated: %s", self.config)
            self.hass.config_entries.async_update_entry(self.entry, data=self.config)
            return self.async_create_entry(data={})

        options_schema = vol.Schema({
            vol.Required(CONF_PERSISTENT_CONNECTION, default=self.config.get(CONF_PERSISTENT_CONNECTION, DEFAULT_PERSISTENT_CONNECTION)): cv.boolean
        })

        return self.async_show_form(
            step_id="settings",
            data_schema=options_schema,
        )
