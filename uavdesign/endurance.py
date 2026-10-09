"""Battery endurance with Peukert correction — platform-agnostic.

This module is the seam between airframes and energy. Every platform reduces
its flight to *pack current* (or electrical power) per mission segment:

* multirotor: hover shaft power from momentum theory  -> electrical -> current
* fixed wing: drag * airspeed / eta_prop               -> electrical -> current

and from there battery sizing, reserve handling and Peukert losses are shared.

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

    @property
    def reference_current_a(self) -> float:
        return self.capacity_ah * self.reference_c_rate

    @property
    def energy_wh(self) -> float:
        """Rated energy at the reference rate (Wh)."""
        return self.capacity_ah * self.nominal_voltage_v


def peukert_efficiency(
    discharge_current_a: float,
    capacity_ah: float,
    peukert_exponent: float,
    reference_c_rate: float = 1.0,
) -> float:
    """Effective capacity multiplier at a given discharge current.

    eta = (I_ref / I)^(n - 1)

    where I_ref is the current implied by the reference C-rate. eta == 1 at the
    reference rate, < 1 above it (typical multirotor hover), > 1 below it
    (typical fixed-wing cruise — small packs at well under 1C).
    """
    if discharge_current_a <= 0:
        return 1.0
    i_ref = capacity_ah * reference_c_rate
    return (i_ref / discharge_current_a) ** (peukert_exponent - 1.0)


def pack_current_a(electrical_power_w: float, pack_voltage_v: float) -> float:
    """Convert electrical power at the pack to pack current."""
    if pack_voltage_v <= 0:
        raise ValueError("pack_voltage_v must be positive")
    return electrical_power_w / pack_voltage_v


def endurance_min(
    battery: Battery,
    current_a: float,
    apply_peukert: bool = True,
) -> float:
    """Endurance (minutes) at a constant pack current.

    Uses usable capacity (reserve already applied) and an optional Peukert
    correction at the discharge current. Works for any platform.
    """
    if current_a <= 0:
        return float("inf")
    eta = (
        peukert_efficiency(
            current_a,
            battery.capacity_ah,
            battery.peukert_exponent,
            battery.reference_c_rate,
        )
        if apply_peukert
        else 1.0
    )
    hours = (battery.usable_capacity_ah * eta) / current_a
    return hours * 60.0


def endurance_from_power_min(
    battery: Battery,
    electrical_power_w: float,
    apply_peukert: bool = True,
) -> float:
    """Endurance (minutes) at a constant electrical power, at nominal voltage."""
    return endurance_min(
        battery,
        pack_current_a(electrical_power_w, battery.nominal_voltage_v),
        apply_peukert,
    )


def hover_endurance_min(
    battery: Battery,
    hover_current_a: float,
    apply_peukert: bool = True,
) -> float:
    """Multirotor-flavoured alias of :func:`endurance_min` (kept for clarity)."""
    return endurance_min(battery, hover_current_a, apply_peukert)


def hover_current_from_power(power_w: float, pack_voltage_v: float) -> float:
    """Backward-compatible alias of :func:`pack_current_a`."""
    return pack_current_a(power_w, pack_voltage_v)


def sweep_capacity(
    capacities_ah,
    current_a: float,
    nominal_voltage_v: float = 22.2,
    peukert_exponent: float = 1.10,
    usable_fraction: float = 0.80,
):
    """Vectorised endurance sweep over battery capacity at a fixed pack current.

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
        minutes[i] = endurance_min(b, current_a)
    return minutes


# --------------------------------------------------------------------------- #
# Mission profiles: segments with different power levels
# --------------------------------------------------------------------------- #

@dataclass
class MissionSegment:
    """One leg of a mission at a constant electrical power."""

    name: str
    duration_s: float
    electrical_power_w: float


def peukert_equivalent_ah(battery: Battery, segments: list[MissionSegment]) -> float:
    """Capacity consumed by a mission, expressed at the battery's reference rate.

    Each segment draws I_i for t_i. Under Peukert, drawing I_i costs
    I_i * t_i * (I_i / I_ref)^(n-1) of reference-rate capacity. Summing these
    lets segments at very different currents (launch climb vs loiter, or
    hover vs transit) share one pack honestly. For a single segment this
    reduces exactly to :func:`endurance_min`.
    """
    total = 0.0
    n = battery.peukert_exponent
    i_ref = battery.reference_current_a
    for seg in segments:
        i = pack_current_a(seg.electrical_power_w, battery.nominal_voltage_v)
        if i <= 0:
            continue
        total += i * (seg.duration_s / 3600.0) * (i / i_ref) ** (n - 1.0)
    return total


def mission_margin(battery: Battery, segments: list[MissionSegment]) -> float:
    """Usable capacity left after the mission as a fraction of usable capacity.

    >= 0 means the mission fits inside the reserve-protected capacity.
    """
    used = peukert_equivalent_ah(battery, segments)
    return 1.0 - used / battery.usable_capacity_ah
