"""Mass-closure sizing for the hand-launched survey flying wing.

One iteration:

    AUW guess
      -> wing area from the hand-launch wing-loading limit (stall at release)
      -> planform (AR, taper, sweep) -> aircraft polar (NeuralFoil + build-up)
      -> printed structure mass (same model the CAD measures)
      -> cruise power at the survey speed -> battery for the endurance target
      -> propulsion sized for launch static thrust and climb
      -> new AUW = payload + avionics + structure + battery + propulsion + contingency

repeated until AUW stops moving. The airframe is sized for one payload
configuration; :func:`evaluate` then flies any other configuration on that
fixed airframe and battery.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import propulsion as prop
from .aero.airfoil import DragBuildUp, aircraft_polar, max_thickness
from .aero.polar import DragPolar, FixedWingAero
from .aero.wing import Wing
from .atmosphere import G
from .structures import PrintMaterial, PrintSettings, Tube, wing_panel_mass_g


@dataclass
class SizingInputs:
    # mission / requirement
    payload_mass_kg: float
    payload_power_w: float
    avionics_mass_kg: float
    avionics_power_w: float
    rho: float
    hand_launch_speed_m_s: float
    launch_margin: float
    endurance_min: float
    survey_speed_m_s: float           # upper bound from camera fps / blur
    climb_rate_m_s: float
    launch_static_tw: float
    # planform
    airfoil: str
    aspect_ratio: float
    taper: float
    le_sweep_deg: float
    oswald_e: float
    pod_half_width_mm: float
    pod_length_mm: float
    pod_height_mm: float
    pod_shell_mass_g_per_dm2: float   # printed pod shell areal mass
    fin_area_fraction: float          # fins (both) / wing area
    elevon_chord_fraction: float
    # structure
    wing_print: PrintSettings
    spar: Tube
    spar_length_fraction: float       # main tube length / half span, per side
    hardware_mass_g: float            # screws, magnets, hinges, glue
    # propulsion + energy
    prop_diameter_in: float
    prop_efficiency: float
    motor_efficiency: float
    esc_efficiency: float
    motor_w_per_g: float
    esc_g_per_a: float
    prop_spinner_mass_g: float
    pack_voltage_v: float
    pack_wh_per_kg: float
    battery_usable_fraction: float
    contingency_fraction: float
    clmax_3d_factor: float = 0.90
    trim_clmax_factor: float = 0.85
    roughness_factor: float = 0.15
    misc_cd: float = 0.002
    # Selected hardware (None = use the parametric models above)
    fixed_propulsion_mass_g: dict | None = None     # {"motor": g, "esc": g, "prop_spinner": g}
    fixed_battery_mass_g: float | None = None
    fixed_battery_energy_wh: float | None = None
    structure_mass_override_g: dict | None = None   # e.g. measured from CAD
    extra_spar_mass_g: float = 0.0                  # joiner + rear pin (span-independent)
    # CAD calibration: measured / analytic (written by scripts/build_parts.py)
    wing_mass_factor: float = 1.0
    pod_mass_factor: float = 1.0


@dataclass
class SizingResult:
    converged: bool
    iterations: int
    auw_kg: float
    wing: Wing
    polar: DragPolar
    polar_info: dict
    masses_g: dict
    wing_area_m2: float
    span_m: float
    wing_loading_n_m2: float
    stall_speed_m_s: float
    cruise_speed_m_s: float
    cruise_power_elec_w: float
    climb_power_elec_w: float
    launch_power_elec_w: float
    battery_energy_wh: float
    endurance_min: float = 0.0
    history: list = field(default_factory=list)

    @property
    def max_power_elec_w(self) -> float:
        return max(self.climb_power_elec_w, self.launch_power_elec_w)

    def summary(self) -> dict:
        return {
            "auw_kg": self.auw_kg,
            "span_m": self.span_m,
            "wing_area_m2": self.wing_area_m2,
            "aspect_ratio": self.wing.aspect_ratio,
            "root_chord_mm": self.wing.root_chord_mm,
            "tip_chord_mm": self.wing.tip_chord_mm,
            "panel_root_chord_mm": float(self.wing.chord_at(0.0)),
            "wing_loading_g_dm2": self.wing_loading_n_m2 / G * 10.0,
            "stall_speed_m_s": self.stall_speed_m_s,
            "cruise_speed_m_s": self.cruise_speed_m_s,
            "cl_cruise": 2 * self.auw_kg * G / (1.167 * self.cruise_speed_m_s ** 2 * self.wing_area_m2),
            "cruise_power_elec_w": self.cruise_power_elec_w,
            "max_power_elec_w": self.max_power_elec_w,
            "battery_energy_wh": self.battery_energy_wh,
            "endurance_min": self.endurance_min,
            "cd0": self.polar.cd0,
            "ld_max": self.polar.ld_max,
            **{f"m_{k}_g": v for k, v in self.masses_g.items()},
        }


def _pod_wetted_area_m2(length_mm: float, width_mm: float, height_mm: float) -> float:
    # Prolate-ish body: ~0.75 x (perimeter of the max section) x length
    a, b = width_mm / 2.0, height_mm / 2.0
    perim = math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))
    return 0.75 * perim * length_mm * 1e-6


def build_planform(area_m2: float, aspect_ratio: float, taper: float, le_sweep_deg: float) -> Wing:
    """Trapezoid from the centreline (the pod sits inside the inner part)."""
    span_mm = math.sqrt(aspect_ratio * area_m2) * 1000.0
    half = span_mm / 2.0
    cr = 2.0 * area_m2 * 1e6 / (span_mm * (1.0 + taper))
    return Wing.trapezoidal(cr, cr * taper, half, le_sweep_deg=le_sweep_deg)


def _structure_masses_g(inp: SizingInputs, wing: Wing) -> dict:
    tc = max_thickness(inp.airfoil)
    # Exposed panels start at the pod side
    y0 = inp.pod_half_width_mm
    c0 = float(wing.chord_at(y0))
    ct = wing.tip_chord_mm
    span_exp = wing.half_span_mm - y0
    area_exp = 0.5 * (c0 + ct) * span_exp
    mean_c = 0.5 * (c0 + ct)
    panels = 2.0 * wing_panel_mass_g(area_exp, mean_c, tc, inp.wing_print)
    fins = 2.0 * wing_panel_mass_g(
        inp.fin_area_fraction * wing.area_mm2 / 2.0, 0.6 * ct, 0.08, inp.wing_print
    )
    pod_area_dm2 = _pod_wetted_area_m2(inp.pod_length_mm, 2 * inp.pod_half_width_mm, inp.pod_height_mm) * 100
    pod = inp.pod_shell_mass_g_per_dm2 * pod_area_dm2
    spars = 2.0 * inp.spar.mass_g(inp.spar_length_fraction * wing.half_span_mm) + inp.extra_spar_mass_g
    return {
        "wing_panels": panels * inp.wing_mass_factor,
        "fins": fins * inp.wing_mass_factor,
        "pod": pod * inp.pod_mass_factor,
        "spars": spars,
        "hardware": inp.hardware_mass_g,
    }


def _aero(inp: SizingInputs, wing: Wing, v_ref: float):
    buildup = DragBuildUp(
        pod_length_m=inp.pod_length_mm / 1000,
        pod_max_diameter_m=math.sqrt(2 * inp.pod_half_width_mm * inp.pod_height_mm) / 1000,
        pod_wetted_area_m2=_pod_wetted_area_m2(inp.pod_length_mm, 2 * inp.pod_half_width_mm, inp.pod_height_mm),
        fin_area_m2=inp.fin_area_fraction * wing.area_m2,
        roughness_factor=inp.roughness_factor,
        misc_cd=inp.misc_cd,
    )
    sweep_c4 = wing.placed_panels[0].sweep_deg_at(0.25)
    return aircraft_polar(
        inp.airfoil, wing.area_m2, wing.aspect_ratio, wing.mac_mm / 1000, v_ref,
        inp.oswald_e, sweep_c4, buildup, inp.clmax_3d_factor, inp.trim_clmax_factor,
    )


def _elec(inp: SizingInputs, shaft_w: float) -> float:
    return prop.electrical_power_w(shaft_w, inp.motor_efficiency, inp.esc_efficiency)


def cruise_speed(ac: FixedWingAero, survey_speed_m_s: float, stall_margin: float = 1.3) -> float:
    """Fly at best-L/D, but never below margin x stall and never above the survey limit."""
    v = max(ac.v_max_ld, stall_margin * ac.stall_speed())
    return min(v, max(survey_speed_m_s, stall_margin * ac.stall_speed()))


def size(inp: SizingInputs, auw_guess_kg: float = 3.0, tol_kg: float = 1e-4, max_iter: int = 60) -> SizingResult:
    auw = auw_guess_kg
    history = []
    polar = None
    v_ref = 14.0
    for it in range(1, max_iter + 1):
        w = auw * G
        # 1) launch-limited wing loading (needs CLmax -> polar; lag one iteration)
        cl_max = polar.cl_max if polar else 0.9
        vs_max = inp.hand_launch_speed_m_s / inp.launch_margin
        ws = 0.5 * inp.rho * vs_max ** 2 * cl_max
        area = w / ws
        wing = build_planform(area, inp.aspect_ratio, inp.taper, inp.le_sweep_deg)
        polar, pinfo = _aero(inp, wing, v_ref)
        ac = FixedWingAero(auw, wing.area_m2, polar, inp.rho)
        v_cr = cruise_speed(ac, inp.survey_speed_m_s)
        v_ref = v_cr
        # 2) power
        p_cr = _elec(inp, prop.cruise_shaft_power_w(float(ac.drag_n(v_cr)), v_cr, inp.prop_efficiency))
        p_cr_total = p_cr + inp.avionics_power_w + inp.payload_power_w
        v_cl = max(1.3 * ac.stall_speed(), ac.v_min_power)
        p_climb = _elec(inp, prop.climb_shaft_power_w(
            float(ac.drag_n(v_cl)), v_cl, w, inp.climb_rate_m_s, inp.prop_efficiency))
        d_prop = inp.prop_diameter_in * 0.0254
        p_launch = _elec(inp, prop.prop_power_estimate(
            inp.launch_static_tw * w, math.pi * d_prop ** 2 / 4, inp.rho, figure_of_merit=0.65))
        p_max = max(p_climb, p_launch)
        # 3) energy
        if inp.fixed_battery_energy_wh is not None:
            e_wh = inp.fixed_battery_energy_wh
            m_batt = inp.fixed_battery_mass_g
        else:
            e_wh = p_cr_total * inp.endurance_min / 60.0 / inp.battery_usable_fraction
            m_batt = e_wh / inp.pack_wh_per_kg * 1000.0
        endurance = e_wh * inp.battery_usable_fraction / p_cr_total * 60.0
        # 4) masses
        m_struct = inp.structure_mass_override_g or _structure_masses_g(inp, wing)
        i_max = p_max / inp.pack_voltage_v
        m_prop = inp.fixed_propulsion_mass_g or {
            "motor": p_max / inp.motor_w_per_g,
            "esc": 10.0 + inp.esc_g_per_a * i_max * 1.3,
            "prop_spinner": inp.prop_spinner_mass_g,
        }
        masses = {
            "payload": inp.payload_mass_kg * 1000,
            "avionics": inp.avionics_mass_kg * 1000,
            **{f"struct_{k}": v for k, v in m_struct.items()},
            **{f"prop_{k}": v for k, v in m_prop.items()},
            "battery": m_batt,
        }
        dry = sum(masses.values())
        masses["contingency"] = inp.contingency_fraction * (dry - m_batt - inp.payload_mass_kg * 1000)
        auw_new = sum(masses.values()) / 1000.0
        history.append(auw_new)
        if abs(auw_new - auw) < tol_kg:
            auw = auw_new
            converged = True
            break
        auw = 0.5 * auw + 0.5 * auw_new  # damped
    else:
        converged = False

    return SizingResult(
        converged=converged,
        iterations=it,
        auw_kg=auw,
        wing=wing,
        polar=polar,
        polar_info=pinfo,
        masses_g=masses,
        wing_area_m2=wing.area_m2,
        span_m=wing.span_mm / 1000,
        wing_loading_n_m2=auw * G / wing.area_m2,
        stall_speed_m_s=FixedWingAero(auw, wing.area_m2, polar, inp.rho).stall_speed(),
        cruise_speed_m_s=v_cr,
        cruise_power_elec_w=p_cr_total,
        climb_power_elec_w=p_climb,
        launch_power_elec_w=p_launch,
        battery_energy_wh=e_wh,
        endurance_min=endurance,
        history=history,
    )


@dataclass
class Evaluation:
    config: str
    auw_kg: float
    wing_loading_g_dm2: float
    stall_speed_m_s: float
    launch_speed_needed_m_s: float
    cruise_speed_m_s: float
    cruise_power_w: float
    endurance_min: float


def evaluate(
    result: SizingResult,
    inp: SizingInputs,
    config: str,
    payload_mass_kg: float,
    payload_power_w: float,
    battery_energy_wh: float | None = None,
    battery_mass_g: float | None = None,
) -> Evaluation:
    """Fly a payload configuration on the sized airframe (fixed wing + battery)."""
    e_wh = battery_energy_wh if battery_energy_wh is not None else result.battery_energy_wh
    m_batt = battery_mass_g if battery_mass_g is not None else result.masses_g["battery"]
    base = result.auw_kg * 1000 - result.masses_g["payload"] - result.masses_g["battery"]
    auw = (base + payload_mass_kg * 1000 + m_batt) / 1000
    ac = FixedWingAero(auw, result.wing_area_m2, result.polar, inp.rho)
    v = cruise_speed(ac, inp.survey_speed_m_s)
    p = _elec(inp, prop.cruise_shaft_power_w(float(ac.drag_n(v)), v, inp.prop_efficiency))
    p_tot = p + inp.avionics_power_w + payload_power_w
    return Evaluation(
        config=config,
        auw_kg=auw,
        wing_loading_g_dm2=auw / result.wing_area_m2 * 10,
        stall_speed_m_s=ac.stall_speed(),
        launch_speed_needed_m_s=ac.stall_speed() * inp.launch_margin,
        cruise_speed_m_s=v,
        cruise_power_w=p_tot,
        endurance_min=e_wh * inp.battery_usable_fraction / p_tot * 60,
    )


def spar_tube(d: dict, spars: dict) -> Tube:
    return Tube(d["od_mm"], d["id_mm"], spars.get("density_g_cm3", 1.55),
                spars.get("allowable_mpa", 400.0), spars.get("modulus_gpa", 110.0))


def spar_set(spars: dict, pod_width_mm: float) -> tuple[Tube, float, float]:
    """(outer swept spar tube, its length / half span, fixed-length tubes mass in g).

    Fixed-length tubes: the joiner, two sleeves and the rear pin; their mass
    does not scale with span inside the sizing loop.
    """
    j, sl, o, rp = spars["joiner"], spars["sleeve"], spars["outer_spar"], spars["rear_pin"]
    sleeve_len = j["half_length_mm"] - pod_width_mm / 2 + 15.0
    fixed = (
        spar_tube(j, spars).mass_g(2 * j["half_length_mm"])
        + 2 * spar_tube(sl, spars).mass_g(sleeve_len)
        + spar_tube(rp, spars).mass_g(2 * rp["half_length_mm"])
    )
    return spar_tube(o, spars), o["y_end_fraction"] - o["y_start_fraction"], fixed


def inputs_from_yaml(design: dict, payload_mass_kg: float, payload_power_w: float,
                     avionics_mass_kg: float, avionics_power_w: float, rho: float,
                     survey_speed_m_s: float) -> SizingInputs:
    """Build :class:`SizingInputs` from ``platforms/survey_wing/design_point.yaml``."""
    req, pl, st, pr, bt = (design[k] for k in ("requirements", "planform", "structure", "propulsion", "battery"))
    mat = PrintMaterial(**st["wing_material"])
    tube, length_fraction, extra = spar_set(st["spars"], design["planform"]["pod_width_mm"])
    cell_wh = bt["cell_capacity_ah"] * bt["cell_nominal_v"]
    pack_wh_per_kg = cell_wh / bt["cell_mass_g"] * 1000 / (1 + bt["pack_overhead_fraction"])
    return SizingInputs(
        payload_mass_kg=payload_mass_kg,
        payload_power_w=payload_power_w,
        avionics_mass_kg=avionics_mass_kg,
        avionics_power_w=avionics_power_w,
        rho=rho,
        hand_launch_speed_m_s=req["hand_launch_speed_m_s"],
        launch_margin=req["launch_margin"],
        endurance_min=req["endurance_min"],
        survey_speed_m_s=survey_speed_m_s,
        climb_rate_m_s=req["climb_rate_m_s"],
        launch_static_tw=req["launch_static_thrust_to_weight"],
        airfoil=pl["airfoil"],
        aspect_ratio=pl["aspect_ratio"],
        taper=pl["taper"],
        le_sweep_deg=pl["le_sweep_deg"],
        oswald_e=pl["oswald_e"],
        pod_half_width_mm=pl["pod_width_mm"] / 2,
        pod_length_mm=pl["pod_length_mm"],
        pod_height_mm=pl["pod_height_mm"],
        pod_shell_mass_g_per_dm2=st["pod_shell_g_per_dm2"],
        fin_area_fraction=pl["fin_area_fraction"],
        elevon_chord_fraction=pl["elevon_chord_fraction"],
        wing_print=PrintSettings(mat, st["wing_perimeters"], st["extrusion_width_mm"], st["wing_infill"]),
        spar=tube,
        spar_length_fraction=length_fraction,
        hardware_mass_g=st["hardware_mass_g"],
        extra_spar_mass_g=extra,
        prop_diameter_in=pr["prop_diameter_in"],
        prop_efficiency=pr["prop_efficiency"],
        motor_efficiency=pr["motor_efficiency"],
        esc_efficiency=pr["esc_efficiency"],
        motor_w_per_g=pr["motor_w_per_g"],
        esc_g_per_a=pr["esc_g_per_a"],
        prop_spinner_mass_g=pr["prop_spinner_mass_g"],
        pack_voltage_v=bt["cells_series"] * bt["cell_nominal_v"],
        pack_wh_per_kg=pack_wh_per_kg,
        battery_usable_fraction=bt["usable_fraction"],
        contingency_fraction=design["contingency_fraction"],
        clmax_3d_factor=pl.get("clmax_3d_factor", 0.90),
        trim_clmax_factor=pl.get("trim_clmax_factor", 0.85),
        roughness_factor=pl.get("roughness_factor", 0.15),
        misc_cd=pl.get("misc_cd", 0.002),
    )
