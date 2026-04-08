"""Toshiba AC IR protocol encoder.

Based on the protocol reverse-engineered by Ilkka Tengvall:
https://github.com/ikke-t/toshiba-ac-ir-remote

Supports Toshiba Heat Pump RAS-10PKVP-ND (remote WH-H07JE) and compatible models.
"""

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
    "auto": MODE_AUTO,
    "cool": MODE_COOL,
    "dry": MODE_DRY,
    "heat": MODE_HEAT,
    "off": MODE_OFF,
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


def encode_command(temp: int = 23, mode: str = "auto", fan: str = "auto", pure: bool = False) -> list[int]:
    """Encode a Toshiba HEAT_PUMP_CMD (on with settings) to IR pulses.

    Args:
        temp: Temperature in Celsius (17-30)
        mode: HVAC mode (auto, cool, dry, heat, off)
        fan: Fan speed (auto, 1, 2, 3, 4, 5)
        pure: Air purifier on/off

    Returns:
        List of pulse timings in microseconds.
    """
    temp = max(TEMP_MIN, min(TEMP_MAX, temp))
    mode_val = HVAC_MODE_MAP.get(mode, MODE_AUTO)
    fan_val = FAN_MODE_MAP.get(fan, FAN_AUTO)

    # Build 9-byte frame
    data = [0xF2, 0x0D, 0x03, 0xFC, 0x01]

    # Byte 5: temp in low nibble
    byte5 = (temp - TEMP_BASE) & 0x0F
    data.append(byte5)

    # Byte 6: fan (high 3 bits) | mode (low nibble)
    byte6 = ((fan_val & 0x07) << 5) | (mode_val & 0x0F)
    data.append(byte6)

    # Byte 7: pure (bit 4)
    byte7 = (0x10 if pure else 0x00)
    data.append(byte7)

    # Byte 8: XOR parity
    data.append(_xor_parity(data))

    return _bytes_to_pulses(data)


def encode_off() -> list[int]:
    """Encode a Toshiba power-off command to IR pulses."""
    return encode_command(temp=TEMP_MIN, mode="off", fan="auto")


def encode_swing() -> list[int]:
    """Encode a Toshiba horizontal swing toggle to IR pulses."""
    return _bytes_to_pulses([0xF2, 0x0D, 0x01, 0xFE, 0x21, 0x04, 0x25])


def encode_vertical() -> list[int]:
    """Encode a Toshiba vertical swing toggle to IR pulses."""
    return _bytes_to_pulses([0xF2, 0x0D, 0x01, 0xFE, 0x21, 0x00, 0x21])


def encode_hi_power() -> list[int]:
    """Encode a Toshiba high-power toggle to IR pulses."""
    return _bytes_to_pulses([0xF2, 0x0D, 0x04, 0xFB, 0x09, 0x00, 0x00, 0x00, 0x01, 0x08])


def encode_sleep() -> list[int]:
    """Encode a Toshiba sleep toggle to IR pulses."""
    return _bytes_to_pulses([0xF2, 0x0D, 0x04, 0xFB, 0x09, 0x00, 0x00, 0x00, 0x03, 0x0A])
