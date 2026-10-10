"""One call that runs the whole survey-wing design chain from the YAMLs.

    requirements + payload -> survey speed limit
    -> free sizing (parametric propulsion + battery)
    -> selected hardware sizing (BOM propulsion masses, discrete pack)
    -> stability (washout for trim at the design static margin)
    -> per-config evaluation on the fixed airframe

Notebooks call :func:`run` and then dig into each step; the CAD generator
reads the resulting planform via :func:`airframe_geometry`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import survey as sv
from .aero import stability as stab
from .atmosphere import isa_density
from .electronics import Electronics
from .payload import SurveyPayload
from .sizing import SizingResult, evaluate, inputs_from_yaml, size

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Design:
    platform_dir: Path
    design: dict
    mission: dict
    electronics: Electronics
    payloads: dict
    rho: float
    survey_speed_limit_m_s: float
    free: SizingResult
    selected: SizingResult
    washout_deg: float
    stability: stab.StabilityResult
    x_cg_target_mm: float
    evaluations: dict
    calibration: dict

    @property
    def wing(self):
        return self.selected.wing


def load(platform: str = "survey_wing", root: Path | None = None) -> tuple[Path, dict, dict]:
    root = root or REPO_ROOT
    pdir = root / "platforms" / platform
    design = yaml.safe_load((pdir / "design_point.yaml").read_text())
    mission = yaml.safe_load((root / "mission" / "mission_params.yaml").read_text())
    return pdir, design, mission


def load_calibration(platform_dir: Path) -> dict:
    """CAD-measured correction factors (written by scripts/build_parts.py), if any."""
    f = platform_dir / "calibration.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text()) or {}


def payload_loads_w(pl: SurveyPayload) -> dict:
    return {
        "camera": pl.cage_members["camera"].get("power_w", 0.0),
        "compute": pl.compute.get("power_w", 0.0),
        "nvme": pl.tray.get("nvme", {}).get("power_w", 0.0),
        "gnss_receiver": pl.cage_members["gnss_receiver"].get("power_w", 0.0),
    }


def survey_speed_limit(design: dict) -> float:
    s = design["survey"]
    cam = sv.Camera.from_dict(s["camera"])
    return min(
        sv.max_ground_speed_m_s(cam, s["agl_m"], s["forward_overlap"]),
        sv.max_speed_for_blur(cam, s["agl_m"], s["exposure_s"], s["blur_limit_px"]),
    )


def run(platform: str = "survey_wing", root: Path | None = None, solve_stability: bool = True,
        calibration: dict | None = None) -> Design:
    """Run the design chain. `calibration` defaults to platforms/<p>/calibration.yaml ({} = analytic only)."""
    root = root or REPO_ROOT
    pdir, design, mission = load(platform, root)
    cal = load_calibration(pdir) if calibration is None else calibration
    elec = Electronics.from_yaml(pdir / "electronics.yaml")
    payload_file = root / design["payload"]["file"]
    payloads = {c: SurveyPayload.from_yaml(payload_file, c, cal.get("cage_structure_g"))
                for c in design["payload"]["configs"]}
    sizing_pl = payloads[design["payload"]["size_for"]]

    rho = isa_density(mission["mission"]["altitude_asl_m"], design["survey"]["hot_day_isa_offset_c"])
    v_survey = survey_speed_limit(design)

    def inputs(pl: SurveyPayload):
        tree = elec.power_tree(payload_loads_w(pl))
        avionics_payload_w = tree["pack_total_w"]
        # sizing splits avionics vs payload power only for bookkeeping
        i = inputs_from_yaml(
            design, pl.mass_kg, avionics_payload_w - elec.avionics_power_w,
            elec.avionics_mass_g / 1000, elec.avionics_power_w, rho, v_survey,
        )
        i.wing_mass_factor = float(cal.get("wing_mass_factor", 1.0))
        i.pod_mass_factor = float(cal.get("pod_mass_factor", 1.0))
        return i

    inp = inputs(sizing_pl)
    free = size(inp)

    pack = elec.pack
    inp.fixed_propulsion_mass_g = elec.propulsion_masses_g
    inp.fixed_battery_mass_g = pack.mass_g
    inp.fixed_battery_energy_wh = pack.energy_wh
    selected = size(inp, auw_guess_kg=free.auw_kg)

    pl = design["planform"]
    pod = (pl["pod_length_mm"], pl["pod_width_mm"])
    if solve_stability:
        cl_cruise = selected.summary()["cl_cruise"]
        washout, st = stab.solve_washout(
            selected.wing, pl["airfoil_root"], pl["airfoil_tip"], cl_cruise, pl["static_margin"],
            pod=pod, blend_start_mm=pl["pod_width_mm"] / 2,
        )
    else:
        washout = 0.0
        st = stab.StabilityResult(0.08, 0.0, selected.wing.x_np_mm, selected.wing.x_np_mm, 0.0, selected.wing.mac_mm)
    x_cg = st.x_np_mm - pl["static_margin"] * st.mac_mm

    evals = {}
    for c, p in payloads.items():
        ic = inputs(p)
        evals[c] = evaluate(selected, ic, c, p.mass_kg, ic.payload_power_w,
                            battery_energy_wh=pack.energy_wh, battery_mass_g=pack.mass_g)

    return Design(pdir, design, mission, elec, payloads, rho, v_survey, free, selected,
                  washout, st, x_cg, evals, cal)


def airframe_geometry(d: Design) -> dict:
    """Geometry the CAD generator needs, in mm / deg."""
    w = d.wing
    pl = d.design["planform"]
    half = w.half_span_mm
    e0, e1 = pl["elevon_span_fraction"]
    return {
        "root_chord_mm": w.root_chord_mm,
        "tip_chord_mm": w.tip_chord_mm,
        "half_span_mm": half,
        "le_sweep_deg": math.degrees(math.atan2(w.placed_panels[0].le_sweep_mm, half)),
        "washout_deg": d.washout_deg,
        "airfoil_root": pl["airfoil_root"],
        "airfoil_tip": pl["airfoil_tip"],
        "pod_width_mm": pl["pod_width_mm"],
        "pod_height_mm": pl["pod_height_mm"],
        "pod_length_mm": pl["pod_length_mm"],
        "fin_height_mm": pl["fin_height_mm"],
        "fin_area_mm2": pl["fin_area_fraction"] * w.area_mm2 / 2,
        "elevon_y_mm": (e0 * half, e1 * half),
        "elevon_chord_fraction": pl["elevon_chord_fraction"],
        "x_np_mm": d.stability.x_np_mm,
        "x_cg_target_mm": d.x_cg_target_mm,
        "mac_mm": w.mac_mm,
        "spars": d.design["structure"]["spars"],
        "prop_diameter_in": d.design["propulsion"]["prop_diameter_in"],
    }
