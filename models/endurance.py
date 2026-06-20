"""Battery endurance with Peukert correction for multirotor hover.

The model is intentionally light: the goal is to support sweeps over capacity
and payload configurations during preliminary sizing, not to replace a
discharge-curve simulator.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Battery:
    """Single-pack model.

    Attributes
    ----------
    capacity_ah : float
        Rated capacity at the manufacturer's reference rate (typically 1C).
    nominal_voltage_v : float
        Nominal pack voltage (e.g. 22.2 V for a 6S LiPo).
    peukert_exponent : float
        Empirical exponent describing capacity loss at high discharge rates.
        Typical values: 1.05 (high-quality Li-ion), 1.10 (LiPo), 1.20+ (NiMH).
    reference_c_rate : float
        C-rate at which `capacity_ah` is rated (almost always 1.0).
    usable_fraction : float
        Fraction of rated capacity treated as usable (reserve margin).
    """

    capacity_ah: float
    nominal_voltage_v: float = 22.2
    peukert_exponent: float = 1.10
    reference_c_rate: float = 1.0
    usable_fraction: float = 0.80  # 20 % reserve

    @property
    def usable_capacity_ah(self) -> float:
        return self.capacity_ah * self.usable_fraction


def peukert_efficiency(
    discharge_current_a: float,
    capacity_ah: float,
    peukert_exponent: float,
    reference_c_rate: float = 1.0,
) -> float:
    """Effective capacity multiplier at a given discharge current.

    eta = (I_ref / I)^(n - 1)

    where I_ref is the current implied by the reference C-rate. eta == 1 at the
    reference rate, < 1 above it, > 1 below it (rare in multirotor hover).
    """
    if discharge_current_a <= 0:
        return 1.0
    i_ref = capacity_ah * reference_c_rate
    return (i_ref / discharge_current_a) ** (peukert_exponent - 1.0)


def hover_endurance_min(
    battery: Battery,
    hover_current_a: float,
    apply_peukert: bool = True,
) -> float:
    """Hover endurance (minutes) for a battery + hover current draw.

    Uses usable capacity (reserve already applied) and an optional Peukert
    correction at the hover current.
    """
    if hover_current_a <= 0:
        return float("inf")
    eta = (
        peukert_efficiency(
            hover_current_a,
            battery.capacity_ah,
            battery.peukert_exponent,
            battery.reference_c_rate,
        )
        if apply_peukert
        else 1.0
    )
    hours = (battery.usable_capacity_ah * eta) / hover_current_a
    return hours * 60.0


def sweep_capacity(
    capacities_ah,
    hover_current_a: float,
    nominal_voltage_v: float = 22.2,
    peukert_exponent: float = 1.10,
    usable_fraction: float = 0.80,
):
    """Vectorised endurance sweep over battery capacity.

    Returns a numpy array of endurance (min), same shape as `capacities_ah`.
    """
    cap = np.asarray(capacities_ah, dtype=float)
    minutes = np.empty_like(cap)
    for i, c in np.ndenumerate(cap):
        b = Battery(
            capacity_ah=float(c),
            nominal_voltage_v=nominal_voltage_v,
            peukert_exponent=peukert_exponent,
            usable_fraction=usable_fraction,
        )
        minutes[i] = hover_endurance_min(b, hover_current_a)
    return minutes


def hover_current_from_power(power_w: float, pack_voltage_v: float) -> float:
    """Convert hover shaft power (or electrical power) to pack current."""
    if pack_voltage_v <= 0:
        raise ValueError("pack_voltage_v must be positive")
    return power_w / pack_voltage_v
