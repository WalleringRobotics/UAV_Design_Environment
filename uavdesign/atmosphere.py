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
    return T0_K - LAPSE_K_M * np.asarray(altitude_m, dtype=float) + temperature_offset_c


def isa_density(altitude_m, temperature_offset_c: float = 0.0):
    """ISA density (kg/m^3) in the troposphere (< 11 km).

    Pressure follows the standard-day profile; the temperature offset only
    changes density through the gas law (the usual "ISA+dT" convention).
    Accepts scalars or arrays.
    """
    alt = np.asarray(altitude_m, dtype=float)
    t_std = T0_K - LAPSE_K_M * alt
    p = P0_PA * (t_std / T0_K) ** (G / (R_AIR * LAPSE_K_M))
    rho = p / (R_AIR * (t_std + temperature_offset_c))
    return float(rho) if rho.ndim == 0 else rho


def wing_loading_g_dm2(wing_loading_n_m2):
    """Convert wing loading from N/m^2 to the RC-model unit g/dm^2."""
    return np.asarray(wing_loading_n_m2) / G * 1000.0 / 100.0


def wing_loading_n_m2(wing_loading_g_dm2_):
    """Convert wing loading from g/dm^2 to N/m^2."""
    return np.asarray(wing_loading_g_dm2_) * 100.0 / 1000.0 * G
