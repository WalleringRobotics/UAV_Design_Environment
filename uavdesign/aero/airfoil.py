"""Airfoil coordinates and section polars.

Coordinates come from AeroSandbox's bundled UIUC database; section
aerodynamics from NeuralFoil (a neural surrogate trained on XFoil), which is
fast enough to sweep inside a sizing loop. Both are local — nothing is
downloaded at run time.

The aircraft-level polar is a drag build-up on top of the section data:

    CD0 = cd_profile0 * (1 + roughness)              wing profile drag
        + sum(Cf * FF * Swet / Sref)                 pod, fins
    k   = k_profile + 1 / (pi * AR * e)              profile + induced

which keeps the parabolic :class:`~uavdesign.aero.polar.DragPolar` interface
used everywhere else.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .polar import DragPolar

NU_AIR = 1.5e-5  # kinematic viscosity, m^2/s (~15 C, 500 m)


def reynolds(airspeed_m_s: float, chord_m: float, nu: float = NU_AIR) -> float:
    return airspeed_m_s * chord_m / nu


@lru_cache(maxsize=64)
def _asb_airfoil(name: str, n_points: int):
    import aerosandbox as asb

    af = asb.Airfoil(name)
    if af.coordinates is None:
        raise KeyError(f"airfoil {name!r} not in the AeroSandbox database")
    return af.repanel(n_points_per_side=n_points)


def coordinates(name: str, n_points_per_side: int = 80) -> np.ndarray:
    """Unit-chord coordinates, TE -> upper -> LE -> lower -> TE, shape (N, 2)."""
    return np.array(_asb_airfoil(name, n_points_per_side).coordinates, dtype=float)


def max_thickness(name: str) -> float:
    return float(_asb_airfoil(name, 80).max_thickness())


def thickness_at(name: str, x_over_c) -> np.ndarray:
    """Local thickness (fraction of chord) at chordwise station(s)."""
    af = _asb_airfoil(name, 80)
    return np.asarray(af.local_thickness(x_over_c=np.asarray(x_over_c, float)))


def camber_at(name: str, x_over_c) -> np.ndarray:
    af = _asb_airfoil(name, 80)
    return np.asarray(af.local_camber(x_over_c=np.asarray(x_over_c, float)))


def section_polar(name: str, reynolds_number: float, alpha_deg=None, model_size: str = "large") -> dict:
    """NeuralFoil section polar. Returns alpha, cl, cd, cm arrays."""
    if alpha_deg is None:
        alpha_deg = np.linspace(-4.0, 16.0, 81)
    af = _asb_airfoil(name, 80)
    r = af.get_aero_from_neuralfoil(alpha=np.asarray(alpha_deg, float), Re=reynolds_number, model_size=model_size)
    return {
        "alpha_deg": np.asarray(alpha_deg, float),
        "cl": np.asarray(r["CL"], float),
        "cd": np.asarray(r["CD"], float),
        "cm": np.asarray(r["CM"], float),
        "confidence": np.asarray(r.get("analysis_confidence", np.ones_like(alpha_deg)), float),
    }


@dataclass(frozen=True)
class SectionSummary:
    name: str
    reynolds: float
    t_over_c: float
    cl_max: float
    alpha_cl_max_deg: float
    cd_min: float
    ld_max: float
    cl_ld_max: float
    cm_at_cl_design: float
    cl_design: float

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def summarize(name: str, reynolds_number: float, cl_design: float = 0.4) -> SectionSummary:
    """Headline section numbers used to compare candidate airfoils."""
    p = section_polar(name, reynolds_number)
    cl, cd, cm, a = p["cl"], p["cd"], p["cm"], p["alpha_deg"]
    i_max = int(np.argmax(cl))
    ld = cl / cd
    j = int(np.argmax(ld))
    pre = slice(0, i_max + 1)  # only the attached branch, below stall
    cm_d = float(np.interp(cl_design, cl[pre], cm[pre]))
    return SectionSummary(
        name=name,
        reynolds=reynolds_number,
        t_over_c=max_thickness(name),
        cl_max=float(cl[i_max]),
        alpha_cl_max_deg=float(a[i_max]),
        cd_min=float(cd.min()),
        ld_max=float(ld[j]),
        cl_ld_max=float(cl[j]),
        cm_at_cl_design=cm_d,
        cl_design=cl_design,
    )


# --------------------------------------------------------------------------- #
# Aircraft polar build-up
# --------------------------------------------------------------------------- #

def skin_friction_turbulent(re: float) -> float:
    """Flat-plate turbulent Cf (Prandtl-Schlichting form used in Raymer)."""
    return 0.455 / (math.log10(re) ** 2.58)


def body_form_factor(fineness: float) -> float:
    """Raymer fuselage form factor, FF = 1 + 60/f^3 + f/400."""
    return 1.0 + 60.0 / fineness ** 3 + fineness / 400.0


@dataclass
class DragBuildUp:
    """Inputs for :func:`aircraft_polar` beyond the wing itself."""

    pod_length_m: float
    pod_max_diameter_m: float
    pod_wetted_area_m2: float
    fin_area_m2: float = 0.0            # total planform area of all fins (one side each)
    roughness_factor: float = 0.15      # printed layer lines, gaps, hinge lines
    misc_cd: float = 0.002              # antenna mast, pitot, motor mount, cooling


def aircraft_polar(
    airfoil: str,
    wing_area_m2: float,
    aspect_ratio: float,
    mean_chord_m: float,
    airspeed_m_s: float,
    oswald_e: float,
    sweep_c4_deg: float,
    buildup: DragBuildUp,
    clmax_3d_factor: float = 0.90,
    trim_clmax_factor: float = 0.85,
    fit_cl_range=(0.1, 0.8),
) -> tuple[DragPolar, dict]:
    """Parabolic aircraft polar from section data + component build-up.

    CLmax: section clmax x 3-D factor x cos(sweep_c4) x trim factor. The trim
    factor covers the up-elevon a tailless wing needs near stall.
    """
    re = reynolds(airspeed_m_s, mean_chord_m)
    p = section_polar(airfoil, re)
    cl, cd = p["cl"], p["cd"]
    i_max = int(np.argmax(cl))
    att = slice(0, i_max + 1)
    m = (cl[att] >= fit_cl_range[0]) & (cl[att] <= fit_cl_range[1])
    A = np.vstack([np.ones(m.sum()), cl[att][m] ** 2]).T
    (cd_p0, k_p), *_ = np.linalg.lstsq(A, cd[att][m], rcond=None)
    k_p = max(float(k_p), 0.0)

    cd_wing = float(cd_p0) * (1.0 + buildup.roughness_factor)
    re_pod = reynolds(airspeed_m_s, buildup.pod_length_m)
    cd_pod = (
        skin_friction_turbulent(re_pod)
        * body_form_factor(buildup.pod_length_m / buildup.pod_max_diameter_m)
        * buildup.pod_wetted_area_m2
        / wing_area_m2
    )
    cd_fins = float(cd_p0) * 1.1 * 2.0 * buildup.fin_area_m2 / wing_area_m2 if buildup.fin_area_m2 else 0.0
    cd0 = cd_wing + cd_pod + cd_fins + buildup.misc_cd
    k = k_p + 1.0 / (math.pi * aspect_ratio * oswald_e)
    cl_max = float(cl[i_max]) * clmax_3d_factor * math.cos(math.radians(sweep_c4_deg)) * trim_clmax_factor

    info = {
        "reynolds": re,
        "section_cl_max": float(cl[i_max]),
        "cd_profile0": float(cd_p0),
        "k_profile": k_p,
        "cd0_wing": cd_wing,
        "cd0_pod": cd_pod,
        "cd0_fins": cd_fins,
        "cd0_misc": buildup.misc_cd,
        "cd0": cd0,
        "k_induced": 1.0 / (math.pi * aspect_ratio * oswald_e),
        "k": k,
        "cl_max": cl_max,
    }
    return DragPolar(cd0=cd0, k=k, cl_max=cl_max), info
