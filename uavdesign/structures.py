"""Printed-airframe structure: mass estimates, spar tubes, control loads.

The printed-part mass model is the same one the CAD pipeline evaluates on real
geometry (``uavdesign.fab.massprops``):

    m = rho * (A_surface * t_wall * n_perimeters + infill * (V - A_surface * t_wall))

so the analytic estimate used in sizing and the CAD-measured value differ only
by how well the analytic surface/volume approximations match the solids.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .atmosphere import G

_trapz = getattr(np, "trapezoid", None) or np.trapz  # numpy 1.x / 2.x

# --------------------------------------------------------------------------- #
# Materials (printed and bought-in)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PrintMaterial:
    name: str
    density_g_cm3: float        # as printed (foamed density for LW grades)
    max_service_c: float
    note: str = ""


@dataclass(frozen=True)
class PrintSettings:
    """What the slicer will do to a part — and therefore what it weighs."""

    material: PrintMaterial
    perimeters: int = 1
    extrusion_width_mm: float = 0.45
    infill_fraction: float = 0.0
    layer_height_mm: float = 0.2

    @property
    def wall_mm(self) -> float:
        return self.perimeters * self.extrusion_width_mm


def printed_mass_g(surface_area_mm2: float, volume_mm3: float, s: PrintSettings) -> float:
    """Mass of a printed part from its outer surface area and enclosed volume."""
    shell_vol = surface_area_mm2 * s.wall_mm
    inner = max(volume_mm3 - shell_vol, 0.0)
    vol = min(shell_vol + s.infill_fraction * inner, volume_mm3)
    return vol * s.material.density_g_cm3 * 1e-3


@dataclass(frozen=True)
class Tube:
    """Round carbon tube (pultruded or roll-wrapped)."""

    od_mm: float
    id_mm: float
    density_g_cm3: float = 1.55
    allowable_mpa: float = 400.0     # conservative for pultruded CF in bending
    modulus_gpa: float = 110.0

    @property
    def area_mm2(self) -> float:
        return math.pi / 4.0 * (self.od_mm ** 2 - self.id_mm ** 2)

    @property
    def second_moment_mm4(self) -> float:
        return math.pi / 64.0 * (self.od_mm ** 4 - self.id_mm ** 4)

    def mass_g(self, length_mm: float) -> float:
        return self.area_mm2 * length_mm * self.density_g_cm3 * 1e-3

    def bending_stress_mpa(self, moment_n_mm: float) -> float:
        return moment_n_mm * (self.od_mm / 2.0) / self.second_moment_mm4


# --------------------------------------------------------------------------- #
# Wing loads
# --------------------------------------------------------------------------- #

def root_bending_moment_n_mm(
    weight_n: float,
    half_span_mm: float,
    load_factor: float,
    station_mm: float = 0.0,
    taper: float = 0.5,
) -> float:
    """Bending moment at `station_mm` from the centreline, one half-wing.

    Lift per side is n*W/2 with a Schrenk-like distribution (mean of the
    trapezoidal planform and the ellipse), integrated numerically. Inertia
    relief is ignored (conservative).
    """
    y = np.linspace(0.0, half_span_mm, 801)
    eta = y / half_span_mm
    trap = 1.0 - (1.0 - taper) * eta
    ell = np.sqrt(np.clip(1.0 - eta ** 2, 0.0, 1.0))
    w = 0.5 * (trap / _trapz(trap, y) + ell / _trapz(ell, y))
    lift = load_factor * weight_n / 2.0 * w          # N/mm
    m = y >= station_mm
    return float(_trapz(lift[m] * (y[m] - station_mm), y[m]))


@dataclass(frozen=True)
class SparCheck:
    station_mm: float
    moment_n_mm: float
    stress_mpa: float
    allowable_mpa: float
    reserve_factor: float


def check_spar(
    tube: Tube,
    weight_n: float,
    half_span_mm: float,
    load_factor: float,
    safety_factor: float,
    station_mm: float,
    taper: float = 0.5,
    share: float = 1.0,
) -> SparCheck:
    """Stress check of a spar tube at a station. `share` = fraction of the moment it carries."""
    m = root_bending_moment_n_mm(weight_n, half_span_mm, load_factor, station_mm, taper) * share
    s = tube.bending_stress_mpa(m * safety_factor)
    return SparCheck(station_mm, m, s, tube.allowable_mpa, tube.allowable_mpa / s)


# --------------------------------------------------------------------------- #
# Control surfaces
# --------------------------------------------------------------------------- #

def servo_torque_kg_cm(
    surface_chord_mm: float,
    surface_span_mm: float,
    airspeed_m_s: float,
    surface_deflection_deg: float,
    servo_deflection_deg: float,
) -> float:
    """Required servo torque, kg*cm (the classic Chief Aircraft RC formula).

    torque[oz*in] = 8.5e-6 * C^2 * V^2 * L * sin(S1) * tan(S1) / tan(S2)
    with C, L in cm and V in mph. Rule-of-thumb only — apply a 2x margin.
    """
    c = surface_chord_mm / 10.0
    l = surface_span_mm / 10.0
    v = airspeed_m_s * 2.23694
    s1 = math.radians(surface_deflection_deg)
    s2 = math.radians(servo_deflection_deg)
    oz_in = 8.5e-6 * c ** 2 * v ** 2 * l * math.sin(s1) * math.tan(s1) / math.tan(s2)
    return oz_in * 0.0720078  # oz*in -> kg*cm


# --------------------------------------------------------------------------- #
# Analytic printed-structure estimate used inside the sizing loop
# --------------------------------------------------------------------------- #

def wing_panel_mass_g(
    area_one_side_mm2: float,
    mean_chord_mm: float,
    t_over_c: float,
    s: PrintSettings,
) -> float:
    """Printed mass of one wing panel (skin + infill), from planform numbers.

    Wetted area ~ 2.04 x planform; enclosed volume ~ 0.685 * t * c per unit
    span (area of a ~10 % airfoil section is ~0.685 t c).
    """
    surface = 2.04 * area_one_side_mm2
    span = area_one_side_mm2 / mean_chord_mm
    volume = 0.685 * t_over_c * mean_chord_mm ** 2 * span
    return printed_mass_g(surface, volume, s)


def weight_n(mass_kg: float) -> float:
    return mass_kg * G
