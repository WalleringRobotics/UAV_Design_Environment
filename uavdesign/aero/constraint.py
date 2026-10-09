"""Fixed-wing constraint analysis: required T/W or P/W as a function of W/S.

Classic matching-chart equations (Gudmundsson ch. 3, Brandt et al.), written
for a parabolic polar CD = CD0 + k*CL^2. Each constraint is evaluated at its
own airspeed, which is how small electric aircraft are actually flown:

* cruise     T/W = q*CD0/(W/S) + k/q * (W/S)
* climb      T/W = ROC/V + q*CD0/(W/S) + k/q * (W/S)
* turn       T/W = q*CD0/(W/S) + k*n^2/q * (W/S),   n = 1/cos(bank)
* stall      W/S <= 0.5 * rho * Vs^2 * CLmax         (vertical line)
* launch     W/S <= 0.5 * rho * (V_launch/margin)^2 * CLmax

W/S is in N/m^2 throughout. For electric propeller aircraft the useful
y-axis is shaft power per unit mass, P/m [W/kg] = (T/W) * V * g / eta_prop,
which is what the RC world calls "watts per kilo" (shaft, not electrical).
"""

from __future__ import annotations

import math

import numpy as np

from ..atmosphere import G
from .polar import dynamic_pressure


def cruise_tw(ws_n_m2, rho: float, airspeed_m_s: float, cd0: float, k: float):
    q = dynamic_pressure(rho, airspeed_m_s)
    ws = np.asarray(ws_n_m2, dtype=float)
    return q * cd0 / ws + k / q * ws


def climb_tw(
    ws_n_m2, rho: float, airspeed_m_s: float, cd0: float, k: float, climb_rate_m_s: float
):
    return climb_rate_m_s / airspeed_m_s + cruise_tw(ws_n_m2, rho, airspeed_m_s, cd0, k)


def turn_tw(
    ws_n_m2, rho: float, airspeed_m_s: float, cd0: float, k: float, bank_deg: float
):
    n = 1.0 / math.cos(math.radians(bank_deg))
    q = dynamic_pressure(rho, airspeed_m_s)
    ws = np.asarray(ws_n_m2, dtype=float)
    return q * cd0 / ws + k * n ** 2 / q * ws


def stall_ws_max(rho: float, stall_speed_m_s: float, cl_max: float) -> float:
    """Largest wing loading that still stalls at or below `stall_speed_m_s`."""
    return 0.5 * rho * stall_speed_m_s ** 2 * cl_max


def launch_ws_max(
    rho: float, launch_speed_m_s: float, cl_max: float, margin: float = 1.2
) -> float:
    """Largest wing loading that can be hand/bungee launched at `launch_speed_m_s`.

    The launch speed must exceed stall by `margin` (1.2 -> launch at 1.2 Vs).
    """
    return stall_ws_max(rho, launch_speed_m_s / margin, cl_max)


def power_per_mass_w_kg(tw, airspeed_m_s: float, prop_efficiency: float = 0.60):
    """Convert T/W at an airspeed to required shaft power per kg of aircraft."""
    return np.asarray(tw) * airspeed_m_s * G / prop_efficiency
