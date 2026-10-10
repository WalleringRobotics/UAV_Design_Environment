"""Precise mass properties of printed parts.

CadQuery's default ``Volume()`` / ``Area()`` use a low-order integration that
under-reads B-spline lofts by up to ~20 %; everything here goes through
OCC's adaptive ``BRepGProp`` with an explicit tolerance instead.

Printed mass follows the same shell + infill model as the analytic sizing
estimate (:func:`uavdesign.structures.printed_mass_g`), and the CG weights
the shell at the surface centroid and the infill at the volume centroid.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

from ..structures import PrintMaterial, PrintSettings


def volume_props(shape, eps: float = 1e-6) -> tuple[float, np.ndarray]:
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, p, eps, False, False)
    c = p.CentreOfMass()
    return float(p.Mass()), np.array([c.X(), c.Y(), c.Z()])


def surface_props(shape, eps: float = 1e-6) -> tuple[float, np.ndarray]:
    p = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape.wrapped, p, eps, False)
    c = p.CentreOfMass()
    return float(p.Mass()), np.array([c.X(), c.Y(), c.Z()])


@dataclass(frozen=True)
class PrintedMass:
    volume_mm3: float
    area_mm2: float
    mass_g: float
    cg_mm: np.ndarray
    filament_g: float          # same as mass for FFF (no support allowance)

    def as_dict(self) -> dict:
        return {"volume_cm3": self.volume_mm3 / 1e3, "area_cm2": self.area_mm2 / 1e2,
                "mass_g": self.mass_g, "cg_mm": [float(v) for v in self.cg_mm]}


def settings_from_profile(profile: dict, materials: dict) -> PrintSettings:
    m = materials[profile["material"]]
    mat = PrintMaterial(m["name"], float(m["density_g_cm3"]), float(m.get("max_service_c", 0)))
    return PrintSettings(mat, int(profile["perimeters"]), float(profile["extrusion_width_mm"]),
                         float(profile["infill_fraction"]), float(profile.get("layer_height_mm", 0.2)))


def printed_mass(shape, settings: PrintSettings) -> PrintedMass:
    vol, c_vol = volume_props(shape)
    area, c_area = surface_props(shape)
    shell_vol = min(area * settings.wall_mm, vol)
    infill_vol = settings.infill_fraction * max(vol - shell_vol, 0.0)
    rho = settings.material.density_g_cm3 * 1e-3
    m_shell, m_inf = shell_vol * rho, infill_vol * rho
    m = m_shell + m_inf
    cg = (m_shell * c_area + m_inf * c_vol) / m if m > 0 else c_vol
    return PrintedMass(vol, area, m, cg, m)
