"""AC protocol encoders for LocalTuya RC."""
from __future__ import annotations
from abc import ABC, abstractmethod

from homeassistant.components.climate import HVACMode


class ACProtocol(ABC):
    """Abstract base class for AC IR protocol encoders."""

    @property
    @abstractmethod
    def min_temp(self) -> int:
        """Minimum temperature in Celsius."""

    @property
    @abstractmethod
    def max_temp(self) -> int:
        """Maximum temperature in Celsius."""

    @property
    @abstractmethod
    def hvac_modes(self) -> list[HVACMode]:
        """Supported HVAC modes (always includes OFF)."""

    @property
    @abstractmethod
    def fan_modes(self) -> list[str]:
        """Supported fan mode names."""

    @property
    def has_swing(self) -> bool:
        """Whether this protocol supports swing control."""
        return False

    @property
    def preset_modes(self) -> list[str]:
        """Supported preset mode names (e.g., 'boost', 'eco')."""
        return []

    @abstractmethod
    def encode_state(
        self, mode: HVACMode, temp: int, fan: str, preset: str | None = None
    ) -> list[int]:
        """Encode the full AC state to IR pulse timings.

        When mode is HVACMode.OFF, encodes a power-off command.
        """

    def encode_swing(self, on: bool) -> list[int]:
        """Encode a swing on/off command. Override if has_swing is True."""
        raise NotImplementedError


# Brand registry — maps brand name to protocol class
_BRANDS: dict[str, type[ACProtocol]] = {}


def register_brand(name: str):
    """Decorator to register an AC protocol brand."""
    def decorator(cls: type[ACProtocol]):
        _BRANDS[name] = cls
        return cls
    return decorator


def get_protocol(brand: str) -> ACProtocol | None:
    """Get an ACProtocol instance by brand name, or None if unknown."""
    cls = _BRANDS.get(brand)
    if cls is None:
        return None
    return cls()


def get_supported_brands() -> list[str]:
    """Return list of supported brand names."""
    return list(_BRANDS.keys())


# Import protocol modules to trigger registration
from . import toshiba  # noqa: E402, F401
