"""Propulsion sizing primitives for multirotors.

Functions are intentionally small and unit-explicit so they can be composed
inside notebooks or wrapped as OpenMDAO components.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

G = 9.80665  # m/s^2


def thrust_per_motor(auw_kg: float, n_motors: int, tw_ratio: float) -> float:
    """Required peak thrust per motor to meet the target T/W at AUW.

    Parameters
    ----------
    auw_kg : float
        All-up weight in kilograms.
    n_motors : int
        Number of lifting motors.
    tw_ratio : float
        Required thrust-to-weight ratio (e.g. 2.0 for a typical multirotor).

    Returns
    -------
    float
        Peak thrust per motor in newtons.
    """
    if n_motors <= 0:
        raise ValueError("n_motors must be positive")
    return (auw_kg * G * tw_ratio) / n_motors


def hover_thrust_per_motor(auw_kg: float, n_motors: int) -> float:
    """Steady-hover thrust per motor (T/W = 1)."""
    return thrust_per_motor(auw_kg, n_motors, tw_ratio=1.0)


def motor_kv_estimate(voltage_v: float, rpm_target: float) -> float:
    """Estimate motor KV (rpm/V) for an unloaded RPM target at a given pack voltage.

    Real motors sag ~15-25 % under load; treat the result as an upper bound.
    """
    if voltage_v <= 0:
        raise ValueError("voltage_v must be positive")
    return rpm_target / voltage_v


def disc_area_m2(prop_diameter_in: float, n_motors: int) -> float:
    """Total rotor disc area (m^2) for `n_motors` props of a given diameter (in)."""
    radius_m = (prop_diameter_in * 0.0254) / 2.0
    return n_motors * math.pi * radius_m ** 2


def isa_density(altitude_m: float, temperature_offset_c: float = 0.0) -> float:
    """ISA atmospheric density (kg/m^3) at an altitude with optional ISA + offset.

    Valid for the troposphere (<11 km), which covers all multirotor missions.
    """
    T0 = 288.15  # K, sea-level standard
    L = 0.0065   # K/m, lapse rate
    p0 = 101325.0  # Pa
    R = 287.058  # J/(kg*K)
    T = T0 - L * altitude_m + temperature_offset_c
    p = p0 * (T / T0) ** (G / (R * L))
    return p / (R * T)


def prop_power_estimate(
    thrust_n: float,
    disc_area_m2: float,
    air_density: float = 1.225,
    figure_of_merit: float = 0.7,
) -> float:
    """Ideal-momentum-theory shaft power (W) corrected by a figure of merit.

    P = (T^(3/2)) / (FM * sqrt(2 * rho * A))

    The FM lumps tip losses, profile drag, and swirl. 0.65–0.75 is realistic for
    well-matched multirotor props at hover.
    """
    if thrust_n <= 0:
        return 0.0
    if disc_area_m2 <= 0:
        raise ValueError("disc_area_m2 must be positive")
    if not (0 < figure_of_merit <= 1):
        raise ValueError("figure_of_merit must be in (0, 1]")
    return (thrust_n ** 1.5) / (figure_of_merit * math.sqrt(2.0 * air_density * disc_area_m2))


def disc_loading(thrust_total_n: float, disc_area_m2: float) -> float:
    """Disc loading (N/m^2) — lower is more efficient."""
    return thrust_total_n / disc_area_m2


@dataclass
class PropulsionPoint:
    """Summary of a multirotor propulsion design point at hover."""

    auw_kg: float
    n_motors: int
    prop_diameter_in: float
    air_density_kg_m3: float
    figure_of_merit: float = 0.7

    @property
    def hover_thrust_total_n(self) -> float:
        return self.auw_kg * G

    @property
    def hover_thrust_per_motor_n(self) -> float:
        return self.hover_thrust_total_n / self.n_motors

    @property
    def disc_area_total_m2(self) -> float:
        return disc_area_m2(self.prop_diameter_in, self.n_motors)

    @property
    def disc_loading_n_m2(self) -> float:
        return disc_loading(self.hover_thrust_total_n, self.disc_area_total_m2)

    @property
    def hover_power_per_motor_w(self) -> float:
        return prop_power_estimate(
            self.hover_thrust_per_motor_n,
            self.disc_area_total_m2 / self.n_motors,
            self.air_density_kg_m3,
            self.figure_of_merit,
        )

    @property
    def hover_power_total_w(self) -> float:
        return self.hover_power_per_motor_w * self.n_motors
