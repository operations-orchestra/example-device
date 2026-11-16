"""A synthetic HCAL-like example device that fills an Operations Record.

SYNTHETIC, NOT CMS DATA. Detector names follow public CMS naming; every event,
time, run number, reading and logbook line is invented by a seeded generator.
"""
from .config import DeviceConfig, PRESETS, preset
from .generator import generate, SizeBudgetError

__all__ = ["DeviceConfig", "PRESETS", "preset", "generate", "SizeBudgetError"]
