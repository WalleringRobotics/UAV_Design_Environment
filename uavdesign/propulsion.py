"""Propulsion sizing primitives shared by multirotor and fixed-wing platforms.

Two families live here:

* **Rotor (hover)** — momentum theory with a figure of merit. Used by the
  multirotor flow.
* **Propeller (cruise)** — shaft power from drag x airspeed / propeller
  efficiency. Used by the fixed-wing flow.

Both end at the same seam: :func:`electrical_power_w` turns shaft power into
pack-side electrical power, which :mod:`uavdesign.endurance` consumes without
caring which airframe produced it.

Functions are intentionally small and unit-explicit so they can be composed
inside notebooks or wrapped as OpenMDAO components.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .atmosphere import G, isa_density  # noqa: F401  (re-exported for notebooks)


# --------------------------------------------------------------------------- #
# Shared: shaft -> electrical
# --------------------------------------------------------------------------- #

def electrical_power_w(
    shaft_power_w: float,
    motor_efficiency: float = 0.80,
    esc_efficiency: float = 0.95,
) -> float:
    """Pack-side electrical power (W) needed to deliver a shaft power (W)."""
    if not (0 < motor_efficiency <= 1 and 0 < esc_efficiency <= 1):
        raise ValueError("efficiencies must be in (0, 1]")
    if not math.isfinite(shaft_power_w) or shaft_power_w < 0:
        raise ValueError("shaft_power_w must be finite and non-negative")
    return shaft_power_w / (motor_efficiency * esc_efficiency)


@dataclass(frozen=True)
class StaticPropellerPoint:
    """Constant-coefficient *estimate*, not measured propeller performance."""

    rpm: float
    thrust_n: float
    shaft_power_w: float
    electrical_power_w: float
    current_a: float
    tip_speed_m_s: float


def static_propeller_point(
    diameter_in: float, rpm: float, voltage_v: float, rho: float,
    ct: float, cp: float, motor_efficiency: float = 0.82,
    esc_efficiency: float = 0.95,
) -> StaticPropellerPoint:
    """Static thrust and power from explicit CT/CP coefficients.

    With n in revolutions/second: T=CT*rho*n²*D⁴, P=CP*rho*n³*D⁵.
    Conventions: https://m-selig.ae.illinois.edu/props/propDB.html .
    CT/CP must be supplied by the caller and documented as measured or assumed.
    Static coefficients cannot validate cruise advance-ratio performance.
    """
    for name, value in (("diameter_in", diameter_in), ("voltage_v", voltage_v),
                        ("rho", rho), ("ct", ct), ("cp", cp)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    if not math.isfinite(rpm) or rpm < 0:
        raise ValueError("rpm must be finite and non-negative")
    n, diameter_m = rpm / 60, diameter_in * 0.0254
    thrust = ct * rho * n ** 2 * diameter_m ** 4
    shaft = cp * rho * n ** 3 * diameter_m ** 5
    electrical = electrical_power_w(shaft, motor_efficiency, esc_efficiency)
    return StaticPropellerPoint(rpm, thrust, shaft, electrical, electrical / voltage_v,
                               math.pi * diameter_m * n)


def propeller_check(
    *, auw_kg: float, diameter_in: float, motor_kv: float, voltage_v: float,
    rho: float, ct: float, cp: float, loaded_rpm_fraction: float,
    required_static_tw: float, esc_rating_a: float, cruise_electrical_power_w: float,
    motor_efficiency: float = 0.82, esc_efficiency: float = 0.95,
    current_headroom: float = 0.20,
) -> dict:
    """Evaluate thrust and ESC margins at one pack voltage.

    RPM = KV * voltage * loaded_rpm_fraction. Neither motor saturation nor pack
    sag is solved, so this screening estimate requires bench confirmation.
    Cruise input power comes from the aircraft drag/power calculation, not CT.
    """
    for name, value in (("auw_kg", auw_kg), ("motor_kv", motor_kv),
                        ("required_static_tw", required_static_tw), ("esc_rating_a", esc_rating_a)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    if not 0 < loaded_rpm_fraction <= 1 or not math.isfinite(current_headroom) or current_headroom < 0:
        raise ValueError("Invalid loaded RPM fraction or current headroom")
    if not math.isfinite(cruise_electrical_power_w) or cruise_electrical_power_w < 0:
        raise ValueError("cruise_electrical_power_w must be finite and non-negative")
    point = static_propeller_point(diameter_in, motor_kv * voltage_v * loaded_rpm_fraction,
                                  voltage_v, rho, ct, cp, motor_efficiency, esc_efficiency)
    required = auw_kg * G * required_static_tw
    return {
        "voltage_v": voltage_v,
        "rpm": point.rpm,
        "static_thrust_n": point.thrust_n,
        "required_static_thrust_n": required,
        "static_thrust_margin_n": point.thrust_n - required,
        "thrust_pass": point.thrust_n >= required,
        "shaft_power_w": point.shaft_power_w,
        "full_throttle_electrical_power_w": point.electrical_power_w,
        "full_throttle_current_a": point.current_a,
        "esc_required_with_headroom_a": point.current_a * (1 + current_headroom),
        "esc_rating_a": esc_rating_a,
        "esc_pass": point.current_a * (1 + current_headroom) <= esc_rating_a,
        "cruise_pack_current_a": cruise_electrical_power_w / voltage_v,
        "tip_speed_m_s": point.tip_speed_m_s,
        "evidence": "estimated; bench validation required",
    }


# --------------------------------------------------------------------------- #
# Fixed wing: propeller in cruise
# --------------------------------------------------------------------------- #

def cruise_shaft_power_w(
    drag_n: float,
    airspeed_m_s: float,
    prop_efficiency: float = 0.60,
) -> float:
    """Shaft power (W) to hold steady level flight: P = D * V / eta_prop.

    In level, unaccelerated flight thrust equals drag, so the propeller must
    deliver D*V of useful power. 0.55-0.70 is typical for small pusher props
    at cruise; it falls sharply away from the prop's design advance ratio.
    """
    if not (0 < prop_efficiency <= 1):
        raise ValueError("prop_efficiency must be in (0, 1]")
    return drag_n * airspeed_m_s / prop_efficiency


def climb_shaft_power_w(
    drag_n: float,
    airspeed_m_s: float,
    weight_n: float,
    climb_rate_m_s: float,
    prop_efficiency: float = 0.60,
) -> float:
    """Shaft power (W) for a steady climb: P = (D*V + W*ROC) / eta_prop."""
    if not (0 < prop_efficiency <= 1):
        raise ValueError("prop_efficiency must be in (0, 1]")
    return (drag_n * airspeed_m_s + weight_n * climb_rate_m_s) / prop_efficiency


# --------------------------------------------------------------------------- #
# Multirotor: rotor in hover
# --------------------------------------------------------------------------- #


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
