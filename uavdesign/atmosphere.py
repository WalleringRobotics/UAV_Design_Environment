"""ISA atmosphere helpers shared by every platform."""

from __future__ import annotations

import numpy as np

G = 9.80665  # m/s^2

T0_K = 288.15      # sea-level standard temperature
P0_PA = 101325.0   # sea-level standard pressure
LAPSE_K_M = 0.0065  # tropospheric lapse rate
R_AIR = 287.058    # J/(kg*K)
RHO0 = 1.225       # kg/m^3


def isa_temperature_k(altitude_m, temperature_offset_c: float = 0.0):
    """ISA temperature (K) at altitude, with an optional ISA+offset."""
    alt = np.asarray(altitude_m, dtype=float)
    if np.any(~np.isfinite(alt)) or np.any((alt < -1000) | (alt > 11000)):
        raise ValueError("altitude_m must be finite and between -1000 and 11000 m")
    temperature = T0_K - LAPSE_K_M * alt + temperature_offset_c
    if np.any(~np.isfinite(temperature)) or np.any(temperature <= 0):
        raise ValueError("absolute temperature must be finite and positive")
    return temperature


def isa_density(altitude_m, temperature_offset_c: float = 0.0):
    """ISA density (kg/m^3) in the troposphere (< 11 km).

    Pressure follows the standard-day profile; the temperature offset only
    changes density through the gas law (the usual "ISA+dT" convention).
    Accepts scalars or arrays.
    """
    alt = np.asarray(altitude_m, dtype=float)
    temperature = isa_temperature_k(alt, temperature_offset_c)
    t_std = T0_K - LAPSE_K_M * alt
    p = P0_PA * (t_std / T0_K) ** (G / (R_AIR * LAPSE_K_M))
    rho = p / (R_AIR * temperature)
    return float(rho) if rho.ndim == 0 else rho


def wing_loading_g_dm2(wing_loading_n_m2):
    """Convert wing loading from N/m^2 to the RC-model unit g/dm^2."""
    return np.asarray(wing_loading_n_m2) / G * 1000.0 / 100.0


def wing_loading_n_m2(wing_loading_g_dm2_):
    """Convert wing loading from g/dm^2 to N/m^2."""
    return np.asarray(wing_loading_g_dm2_) * 100.0 / 1000.0 * G
