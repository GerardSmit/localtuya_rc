"""Toshiba AC IR protocol encoder.

Based on the protocol reverse-engineered by Ilkka Tengvall:
https://github.com/ikke-t/toshiba-ac-ir-remote

Supports Toshiba Heat Pump RAS-10PKVP-ND (remote WH-H07JE) and compatible models.
"""
from __future__ import annotations

from homeassistant.components.climate import HVACMode, SWING_ON, SWING_OFF

from . import ACProtocol, register_brand

# IR timing constants (microseconds)
HDR_MARK = 4400
HDR_SPACE = 4400
BIT_MARK = 550
ONE_SPACE = 1600
ZERO_SPACE = 550

# Temperature
TEMP_MIN = 17
TEMP_MAX = 30
TEMP_BASE = 17

# HVAC modes (byte 6, low nibble)
MODE_AUTO = 0
MODE_COOL = 1
MODE_DRY = 2
MODE_HEAT = 3
MODE_OFF = 7

# Fan speeds (byte 6, high 3 bits)
FAN_AUTO = 0
FAN_1 = 2
FAN_2 = 3
FAN_3 = 4
FAN_4 = 5
FAN_5 = 6

HVAC_MODE_MAP = {
    HVACMode.AUTO: MODE_AUTO,
    HVACMode.COOL: MODE_COOL,
    HVACMode.DRY: MODE_DRY,
    HVACMode.HEAT: MODE_HEAT,
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
        return [HVACMode.OFF, HVACMode.AUTO, HVACMode.COOL, HVACMode.DRY, HVACMode.HEAT]

    @property
    def fan_modes(self) -> list[str]:
        return ["auto", "1", "2", "3", "4", "5"]

    @property
    def has_swing(self) -> bool:
        return True

    def encode_state(self, mode: HVACMode, temp: int, fan: str) -> list[int]:
        """Encode the full AC state to IR pulse timings."""
        if mode == HVACMode.OFF:
            return self._encode_command(temp=TEMP_MIN, mode_val=MODE_OFF, fan_val=FAN_AUTO)
        mode_val = HVAC_MODE_MAP.get(mode, MODE_AUTO)
        fan_val = FAN_MODE_MAP.get(fan, FAN_AUTO)
        return self._encode_command(temp=temp, mode_val=mode_val, fan_val=fan_val)

    def encode_swing(self) -> list[int]:
        """Encode horizontal swing toggle."""
        return _bytes_to_pulses([0xF2, 0x0D, 0x01, 0xFE, 0x21, 0x04, 0x25])

    @staticmethod
    def _encode_command(temp: int, mode_val: int, fan_val: int, pure: bool = False) -> list[int]:
        """Encode a Toshiba HEAT_PUMP_CMD to IR pulses."""
        temp = max(TEMP_MIN, min(TEMP_MAX, temp))

        data = [0xF2, 0x0D, 0x03, 0xFC, 0x01]
        byte5 = (temp - TEMP_BASE) & 0x0F
        data.append(byte5)
        byte6 = ((fan_val & 0x07) << 5) | (mode_val & 0x0F)
        data.append(byte6)
        byte7 = (0x10 if pure else 0x00)
        data.append(byte7)
        data.append(_xor_parity(data))

        return _bytes_to_pulses(data)
