"""Parabolic drag polar and steady level-flight performance for fixed wings.

    CD = CD0 + k * CL^2,      k = 1 / (pi * AR * e)

Good enough for preliminary sizing of a small electric wing; replace with an
XFLR5 / AVL polar once the airfoil and planform settle. Every speed result is
checked against stall, because on low-aspect-ratio flying wings with
reflexed sections the theoretical minimum-power speed often sits *below* the
stall speed — the airframe is then stall-limited, not drag-limited.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..atmosphere import G


@dataclass(frozen=True)
class DragPolar:
    """CD = cd0 + k * CL^2, valid up to cl_max."""

    cd0: float
    k: float
    cl_max: float

    @classmethod
    def from_oswald(
        cls, cd0: float, aspect_ratio: float, oswald_e: float, cl_max: float
    ) -> "DragPolar":
        if not (0 < oswald_e <= 1):
            raise ValueError("oswald_e must be in (0, 1]")
        return cls(cd0=cd0, k=1.0 / (math.pi * aspect_ratio * oswald_e), cl_max=cl_max)

    def cd(self, cl):
        return self.cd0 + self.k * np.asarray(cl) ** 2

    # ---- optimum lift coefficients (unconstrained by stall) ---------------

    @property
    def cl_max_ld(self) -> float:
        """CL for best L/D (best glide, max range for a prop aircraft)."""
        return math.sqrt(self.cd0 / self.k)

    @property
    def cl_min_power(self) -> float:
        """CL for minimum power required (max endurance for a prop aircraft)."""
        return math.sqrt(3.0 * self.cd0 / self.k)

    @property
    def ld_max(self) -> float:
        return 1.0 / (2.0 * math.sqrt(self.cd0 * self.k))


def dynamic_pressure(rho: float, airspeed_m_s):
    return 0.5 * rho * np.asarray(airspeed_m_s, dtype=float) ** 2


@dataclass
class FixedWingAero:
    """Steady-flight performance of one aircraft at one mass and density.

    Parameters
    ----------
    mass_kg : float
    wing_area_m2 : float
    polar : DragPolar
    rho : float
        Air density (kg/m^3) — use :func:`uavdesign.atmosphere.isa_density`.
    """

    mass_kg: float
    wing_area_m2: float
    polar: DragPolar
    rho: float

    @property
    def weight_n(self) -> float:
        return self.mass_kg * G

    @property
    def wing_loading_n_m2(self) -> float:
        return self.weight_n / self.wing_area_m2

    # ---- speeds -------------------------------------------------------------

    def speed_for_cl(self, cl: float, load_factor: float = 1.0) -> float:
        return math.sqrt(
            2.0 * load_factor * self.weight_n / (self.rho * self.wing_area_m2 * cl)
        )

    def stall_speed(self, load_factor: float = 1.0) -> float:
        return self.speed_for_cl(self.polar.cl_max, load_factor)

    @property
    def v_max_ld(self) -> float:
        """Best-L/D speed, ignoring stall (check against :meth:`stall_speed`)."""
        return self.speed_for_cl(self.polar.cl_max_ld)

    @property
    def v_min_power(self) -> float:
        """Minimum-power speed, ignoring stall (check against :meth:`stall_speed`)."""
        return self.speed_for_cl(self.polar.cl_min_power)

    def stall_limited(self, margin: float = 1.2) -> dict[str, bool]:
        """Which optimum speeds fall below `margin` x stall speed."""
        vs = margin * self.stall_speed()
        return {"v_max_ld": self.v_max_ld < vs, "v_min_power": self.v_min_power < vs}

    # ---- forces and power at airspeed --------------------------------------

    def cl(self, airspeed_m_s, load_factor: float = 1.0):
        q = dynamic_pressure(self.rho, airspeed_m_s)
        return load_factor * self.weight_n / (q * self.wing_area_m2)

    def drag_n(self, airspeed_m_s, load_factor: float = 1.0):
        q = dynamic_pressure(self.rho, airspeed_m_s)
        return q * self.wing_area_m2 * self.polar.cd(self.cl(airspeed_m_s, load_factor))

    def aero_power_w(self, airspeed_m_s, load_factor: float = 1.0):
        """Power required, D*V (W), before propeller/motor/ESC losses."""
        return self.drag_n(airspeed_m_s, load_factor) * np.asarray(airspeed_m_s)

    def lift_to_drag(self, airspeed_m_s):
        cl = self.cl(airspeed_m_s)
        return cl / self.polar.cd(cl)

    def above_stall(self, airspeed_m_s, load_factor: float = 1.0):
        """Boolean mask: CL required is within cl_max."""
        return self.cl(airspeed_m_s, load_factor) <= self.polar.cl_max
