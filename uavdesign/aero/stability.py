"""Longitudinal stability and trim of a tailless wing (vortex lattice).

Uses AeroSandbox's vortex-lattice method on the real planform, with the
airfoil camber lines (so reflex counts), linear twist (washout) and an
optional elevon modelled as a camber change of the outboard sections.

For a tailless aircraft at a CG with static margin SM (fraction of MAC):

    Cm_cg(CL) = Cm0 + (dCm/dCL)_cg * CL,    (dCm/dCL)_cg = -SM

and trim at the cruise CL requires Cm0 = SM * CL_cruise. Washout and a
reflexed tip section raise Cm0; up-elevon ("reflex trim") makes up the rest.

The centre pod is destabilising; its neutral-point shift is estimated with
Raymer's fuselage pitching-moment term (eq. 16.25) and applied on top of the
VLM wing result.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .wing import Wing


@lru_cache(maxsize=512)
def _af(root: str, tip: str, blend: float, flap_deg: float = 0.0, hinge_x: float = 0.78):
    """Section at a station: root/tip blend (0 = root), optionally with a flap."""
    import aerosandbox as asb

    af = asb.Airfoil(root).repanel(n_points_per_side=60)
    if tip != root and blend > 0:
        af = af.blend_with_another_airfoil(asb.Airfoil(tip).repanel(n_points_per_side=60), blend_fraction=blend)
    if flap_deg:
        af = af.add_control_surface(deflection=flap_deg, hinge_point_x=hinge_x)
    return af


def airfoil_blend_fraction(wing: Wing, y_mm: float, blend_start_mm: float = 0.0) -> float:
    """Root->tip airfoil blend: root section inboard of `blend_start_mm`, linear to the tip."""
    if y_mm <= blend_start_mm:
        return 0.0
    return min(1.0, (y_mm - blend_start_mm) / (wing.half_span_mm - blend_start_mm))


@dataclass(frozen=True)
class ElevonSpec:
    y_start_mm: float
    y_end_mm: float
    hinge_x_over_c: float = 0.78


@dataclass(frozen=True)
class WingAeroModel:
    """Everything the VLM needs that is not in :class:`Wing`."""

    root_airfoil: str
    tip_airfoil: str
    washout_deg: float = 0.0          # tip incidence relative to root (positive = nose down)
    elevon: ElevonSpec | None = None
    blend_start_mm: float = 0.0       # root section held constant inboard of this (the pod)


def _stations(wing: Wing, model: WingAeroModel) -> list[float]:
    ys = {0.0, wing.half_span_mm}
    for p in wing.placed_panels:
        ys.add(p.tip_y_mm)
    if 0.0 < model.blend_start_mm < wing.half_span_mm:
        ys.add(model.blend_start_mm)
    ys.add(0.5 * (model.blend_start_mm + wing.half_span_mm))
    if model.elevon:
        ys.update({model.elevon.y_start_mm, model.elevon.y_end_mm})
    return sorted(ys)


def build_airplane(wing: Wing, model: WingAeroModel, elevon_deg: float = 0.0):
    """AeroSandbox Airplane for the wing (reference point = root LE)."""
    import aerosandbox as asb

    xsecs = []
    half = wing.half_span_mm
    for y in _stations(wing, model):
        eta = y / half
        twist = -model.washout_deg * eta
        blend = airfoil_blend_fraction(wing, y, model.blend_start_mm)
        flap = 0.0
        if model.elevon and model.elevon.y_start_mm - 1e-6 <= y <= model.elevon.y_end_mm + 1e-6:
            flap = elevon_deg
        hinge = model.elevon.hinge_x_over_c if model.elevon else 0.78
        xsecs.append(
            asb.WingXSec(
                xyz_le=[float(wing.le_x_at(y)) / 1000, y / 1000, 0.0],
                chord=float(wing.chord_at(y)) / 1000,
                twist=twist,
                airfoil=_af(model.root_airfoil, model.tip_airfoil, round(blend, 4), round(flap, 3), hinge),
            )
        )
    w = asb.Wing(name="wing", symmetric=True, xsecs=xsecs)
    return asb.Airplane(
        "survey_wing", xyz_ref=[0, 0, 0], wings=[w],
        s_ref=w.area(), c_ref=w.mean_aerodynamic_chord(), b_ref=w.span(),
    )


@dataclass(frozen=True)
class StabilityResult:
    cl_alpha_per_deg: float
    cl0: float
    x_np_wing_mm: float
    x_np_mm: float              # including the pod shift
    cm0: float                  # about the neutral point, i.e. Cm at CL = 0 about x_np
    mac_mm: float

    def cm_at(self, cl: float, x_cg_mm: float) -> float:
        sm = (self.x_np_mm - x_cg_mm) / self.mac_mm
        return self.cm0 - sm * cl


def pod_np_shift_mm(
    wing: Wing,
    pod_length_mm: float,
    pod_width_mm: float,
    cl_alpha_per_deg: float,
    k_fus: float = 0.010,
) -> float:
    """Forward NP shift (mm) from the pod, Raymer: Cm_alpha_fus = K W^2 L / (c S) [1/deg]."""
    cm_a = k_fus * pod_width_mm ** 2 * pod_length_mm / (wing.mac_mm * wing.area_mm2)
    return cm_a / cl_alpha_per_deg * wing.mac_mm


def analyse(
    wing: Wing,
    model: WingAeroModel,
    airspeed_m_s: float = 14.0,
    elevon_deg: float = 0.0,
    pod: tuple[float, float] | None = None,
    spanwise_resolution: int = 10,
    chordwise_resolution: int = 8,
) -> StabilityResult:
    """Neutral point and zero-lift moment from two VLM solutions."""
    import aerosandbox as asb

    plane = build_airplane(wing, model, elevon_deg)
    out = []
    for a in (0.0, 4.0):
        r = asb.VortexLatticeMethod(
            plane, asb.OperatingPoint(velocity=airspeed_m_s, alpha=a),
            spanwise_resolution=spanwise_resolution, chordwise_resolution=chordwise_resolution,
        ).run()
        out.append((float(r["CL"]), float(r["Cm"])))
    (cl0, cm_a0), (cl4, cm_a4) = out
    cla = (cl4 - cl0) / 4.0
    dcm_dcl = (cm_a4 - cm_a0) / (cl4 - cl0)
    c = plane.c_ref * 1000
    x_np_w = -dcm_dcl * c                 # about the root LE (xyz_ref = 0)
    cm0_np = cm_a0 - dcm_dcl * cl0        # Cm at CL=0 (independent of reference once at NP)
    shift = pod_np_shift_mm(wing, pod[0], pod[1], cla) if pod else 0.0
    return StabilityResult(cla, cl0, x_np_w, x_np_w - shift, cm0_np, c)


def solve_washout(
    wing: Wing,
    root_airfoil: str,
    tip_airfoil: str,
    cl_trim: float,
    static_margin: float,
    pod: tuple[float, float] | None = None,
    bounds=(-2.0, 12.0),
    airspeed_m_s: float = 14.0,
    blend_start_mm: float = 0.0,
) -> tuple[float, StabilityResult]:
    """Washout (deg) that trims the clean wing at `cl_trim` with `static_margin`."""
    target = static_margin * cl_trim

    def mk(w):
        return WingAeroModel(root_airfoil, tip_airfoil, w, blend_start_mm=blend_start_mm)

    def f(w):
        return analyse(wing, mk(w), airspeed_m_s, pod=pod).cm0 - target

    lo, hi = bounds
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        w = hi if abs(fhi) < abs(flo) else lo
        return w, analyse(wing, mk(w), airspeed_m_s, pod=pod)
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if flo * fm <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
        if hi - lo < 0.02:
            break
    w = 0.5 * (lo + hi)
    return w, analyse(wing, mk(w), airspeed_m_s, pod=pod)


def solve_elevon_trim(
    wing: Wing,
    model: WingAeroModel,
    cl_trim: float,
    x_cg_mm: float,
    pod: tuple[float, float] | None = None,
    bounds=(-15.0, 15.0),
    airspeed_m_s: float = 14.0,
) -> tuple[float, StabilityResult]:
    """Elevon deflection (deg, negative = trailing edge up) for Cm_cg = 0 at `cl_trim`."""
    if model.elevon is None:
        raise ValueError("model has no elevon")

    def f(d):
        return analyse(wing, model, airspeed_m_s, d, pod).cm_at(cl_trim, x_cg_mm)

    lo, hi = bounds
    flo = f(lo)
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if flo * fm <= 0:
            hi = mid
        else:
            lo, flo = mid, fm
        if hi - lo < 0.05:
            break
    d = 0.5 * (lo + hi)
    return d, analyse(wing, model, airspeed_m_s, d, pod)


def panknin_washout_deg(
    cm_root: float, cm_tip: float, a0_root_deg: float, a0_tip_deg: float,
    cl: float, static_margin: float, aspect_ratio: float, taper: float, c4_sweep_deg: float,
) -> float:
    """Panknin's classic flying-wing twist formula — an independent cross-check.

    Twist = [K1*(cm_r + cm_t) - CL*SM] / (1.4e-5 * AR^1.43 * sweep) + (a0_r - a0_t)
    with K1 = 0.25 * (3 + 2 taper + taper^2) / (1 + taper + taper^2).
    """
    k1 = 0.25 * (3 + 2 * taper + taper ** 2) / (1 + taper + taper ** 2)
    num = k1 * (cm_root + cm_tip) - cl * static_margin
    den = 1.4e-5 * aspect_ratio ** 1.43 * c4_sweep_deg
    return -(num / den) + (a0_root_deg - a0_tip_deg)
