"""Toshiba AC IR protocol encoder.

Based on the IRremoteESP8266 library by David Conran et al:
https://github.com/crankyoldgit/IRremoteESP8266

Supports Toshiba AC systems with WH-L03SE, WC-L03SE, WH-TA04NE,
WH-UB03NJ, WH-TA01JE, and compatible remotes.
"""
from __future__ import annotations

from homeassistant.components.climate import HVACMode

from . import ACProtocol, register_brand

# IR timing constants (microseconds) per IRremoteESP8266
HDR_MARK = 4400
HDR_SPACE = 4300
BIT_MARK = 580
ONE_SPACE = 1600
ZERO_SPACE = 490

# Temperature
TEMP_MIN = 17
TEMP_MAX = 30
TEMP_BASE = 17

# HVAC modes (byte 6, bits [2:0])
MODE_AUTO = 0
MODE_COOL = 1
MODE_DRY = 2
MODE_HEAT = 3
MODE_FAN = 4
MODE_OFF = 7

# Fan speeds (byte 6, bits [7:5]) — raw protocol values
FAN_AUTO = 0
FAN_1 = 2
FAN_2 = 3
FAN_3 = 4
FAN_4 = 5
FAN_5 = 6

# Swing modes (byte 5, bits [2:0])
SWING_STEP = 0
SWING_ON = 1
SWING_OFF = 2
SWING_TOGGLE = 4

# Eco/Turbo (byte 8 in 80-bit long messages)
TURBO_ON = 1
ECO_ON = 3

HVAC_MODE_MAP = {
    HVACMode.AUTO: MODE_AUTO,
    HVACMode.COOL: MODE_COOL,
    HVACMode.DRY: MODE_DRY,
    HVACMode.HEAT: MODE_HEAT,
    HVACMode.FAN_ONLY: MODE_FAN,
    HVACMode.OFF: MODE_OFF,
}

FAN_MODE_MAP = {
    "auto": FAN_AUTO,
    "1": FAN_1,
    "2": FAN_2,
    "3": FAN_3,
    "4": FAN_4,
    "5": FAN_5,
}


def _bytes_to_pulses(data: list[int]) -> list[int]:
    """Convert a byte array to IR pulse timings (mark/space pairs), MSB first."""
    pulses = [HDR_MARK, HDR_SPACE]
    for byte_val in data:
        for bit_pos in range(7, -1, -1):
            pulses.append(BIT_MARK)
            if byte_val & (1 << bit_pos):
                pulses.append(ONE_SPACE)
            else:
                pulses.append(ZERO_SPACE)
    # Footer mark
    pulses.append(BIT_MARK)
    return pulses


def _xor_parity(data: list[int]) -> int:
    """Calculate XOR parity of all bytes."""
    parity = 0
    for b in data:
        parity ^= b
    return parity


@register_brand("toshiba")
class ToshibaProtocol(ACProtocol):
    """Toshiba AC IR protocol."""

    @property
    def min_temp(self) -> int:
        return TEMP_MIN

    @property
    def max_temp(self) -> int:
        return TEMP_MAX

    @property
    def hvac_modes(self) -> list[HVACMode]:
        return [HVACMode.OFF, HVACMode.AUTO, HVACMode.COOL, HVACMode.DRY, HVACMode.HEAT, HVACMode.FAN_ONLY]

    @property
    def fan_modes(self) -> list[str]:
        return ["auto", "1", "2", "3", "4", "5"]

    @property
    def has_swing(self) -> bool:
        return True

    @property
    def preset_modes(self) -> list[str]:
        return ["boost", "eco"]

    def encode_state(self, mode: HVACMode, temp: int, fan: str, preset: str | None = None) -> list[int]:
        """Encode the full AC state to IR pulse timings."""
        if mode == HVACMode.OFF:
            return self._encode_command(temp=TEMP_MIN, mode_val=MODE_OFF, fan_val=FAN_AUTO)
        mode_val = HVAC_MODE_MAP.get(mode, MODE_AUTO)
        fan_val = FAN_MODE_MAP.get(fan, FAN_AUTO)
        eco_turbo = None
        if preset == "boost":
            eco_turbo = TURBO_ON
        elif preset == "eco":
            eco_turbo = ECO_ON
        return self._encode_command(
            temp=temp, mode_val=mode_val, fan_val=fan_val, eco_turbo=eco_turbo
        )

    def encode_swing(self, on: bool) -> list[int]:
        """Encode an explicit swing on/off command."""
        return self._encode_swing_command(SWING_ON if on else SWING_OFF)

    @staticmethod
    def _encode_swing_command(swing_mode: int) -> list[int]:
        """Encode a Toshiba swing command (56-bit / 7-byte short message)."""
        data = [0xF2, 0x0D, 0x01, 0xFE, 0x21]
        byte5 = swing_mode & 0x07
        data.append(byte5)
        data.append(_xor_parity(data))
        return _bytes_to_pulses(data)

    @staticmethod
    def _encode_command(
        temp: int, mode_val: int, fan_val: int,
        filter_on: bool = False, eco_turbo: int | None = None,
    ) -> list[int]:
        """Encode a Toshiba AC state command.

        Normal state: 72-bit / 9-byte message.
        With eco/turbo: 80-bit / 10-byte long message.
        """
        temp = max(TEMP_MIN, min(TEMP_MAX, temp))

        if eco_turbo is not None:
            # 80-bit long message: length=4, LongMsg bit set
            data = [0xF2, 0x0D, 0x04, 0xFB, 0x09]
        else:
            # 72-bit normal message: length=3
            data = [0xF2, 0x0D, 0x03, 0xFC, 0x01]
        # Byte 5: temp in high nibble (bits [7:4])
        byte5 = ((temp - TEMP_BASE) & 0x0F) << 4
        data.append(byte5)
        # Byte 6: fan in bits [7:5], mode in bits [2:0]
        byte6 = ((fan_val & 0x07) << 5) | (mode_val & 0x07)
        data.append(byte6)
        # Byte 7: filter/pure in bit 4
        byte7 = 0x10 if filter_on else 0x00
        data.append(byte7)
        # Byte 8 (80-bit only): eco/turbo value
        if eco_turbo is not None:
            data.append(eco_turbo & 0xFF)
        data.append(_xor_parity(data))

        return _bytes_to_pulses(data)
