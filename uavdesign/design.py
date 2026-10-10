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
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from . import survey as sv
from .aero import stability as stab
from .atmosphere import isa_density
from .electronics import Electronics
from .power import cooling_airflow
from .propulsion import propeller_check
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
    cam = replace(cam, max_fps=min(cam.max_fps, s.get("acquisition_rate_cap_hz", cam.max_fps)))
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
    # Keep the legacy mirrored sizing fields honest: the discrete BOM is the
    # pack source of truth. A mismatch must not silently size a different pack.
    for key, value in {
        "cells_series": elec.pack.series, "cell_capacity_ah": elec.pack.cell_capacity_ah,
        "cell_nominal_v": elec.pack.cell_nominal_v, "cell_mass_g": elec.pack.cell_mass_g,
        "pack_overhead_fraction": elec.pack.overhead_fraction,
    }.items():
        if not math.isclose(design["battery"][key], value, rel_tol=1e-9):
            raise ValueError(f"battery.{key} differs from electronics.yaml pack")
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
    if not free.converged:
        raise RuntimeError("Free mass sizing did not converge")

    pack = elec.pack
    inp.fixed_propulsion_mass_g = elec.propulsion_masses_g
    inp.fixed_battery_mass_g = pack.mass_g
    inp.fixed_battery_energy_wh = pack.energy_wh
    selected = size(inp, auw_guess_kg=free.auw_kg)
    if not selected.converged:
        raise RuntimeError("Selected-hardware mass sizing did not converge")

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


def inputs_for(d: Design, config: str | None = None, *, selected: bool = True):
    """Reconstruct sizing inputs from the same payload, pack and calibration.

    Use this for trades so notebook parameters cannot drift from ``run``.
    """
    config = config or d.design["payload"]["size_for"]
    payload = d.payloads[config]
    e = d.electronics
    pack_power = e.power_tree(payload_loads_w(payload))["pack_total_w"]
    inp = inputs_from_yaml(d.design, payload.mass_kg, pack_power - e.avionics_power_w,
                           e.avionics_mass_g / 1000, e.avionics_power_w,
                           d.rho, d.survey_speed_limit_m_s)
    inp.wing_mass_factor = float(d.calibration.get("wing_mass_factor", 1.0))
    inp.pod_mass_factor = float(d.calibration.get("pod_mass_factor", 1.0))
    if selected:
        inp.fixed_propulsion_mass_g = e.propulsion_masses_g
        inp.fixed_battery_mass_g = e.pack.mass_g
        inp.fixed_battery_energy_wh = e.pack.energy_wh
    return inp


def launch_trade(d: Design) -> list[dict]:
    """Re-size selected hardware for hand/bungee release, without selecting it."""
    inp = inputs_for(d)
    req = d.design["requirements"]
    speeds = {"hand": req["hand_launch_speed_m_s"],
              "bungee": req["launch"]["bungee_release_speed_m_s"]}
    results = {mode: size(replace(inp, hand_launch_speed_m_s=speed),
                          auw_guess_kg=d.selected.auw_kg) for mode, speed in speeds.items()}
    baseline_area = results["hand"].wing_area_m2
    return [{"launch": mode, "selected": mode == req["launch"]["selected"],
             "release_speed_m_s": speeds[mode], "converged": result.converged,
             "auw_kg": result.auw_kg, "wing_area_m2": result.wing_area_m2,
             "span_m": result.span_m, "endurance_min": result.endurance_min,
             "survey_speed_compatible": result.survey_speed_compatible,
             "area_saving_fraction": 1 - result.wing_area_m2 / baseline_area,
             "qualification": "sizing trade only; launch loads and CAD require revalidation"}
            for mode, result in results.items()]


def battery_trade(d: Design, parallels=(1, 2), config: str | None = None) -> list[dict]:
    """Re-fly a fixed airframe for each actual pack mass and energy."""
    inp = inputs_for(d, config)
    config = config or d.design["payload"]["size_for"]
    rows = []
    for parallel in parallels:
        pack = d.electronics.pack.with_parallel(parallel)
        ev = evaluate(d.selected, inp, config, inp.payload_mass_kg, inp.payload_power_w,
                      battery_energy_wh=pack.energy_wh, battery_mass_g=pack.mass_g)
        rows.append({"pack": pack.label, "mass_g": pack.mass_g, "energy_wh": pack.energy_wh,
                     **ev.__dict__,
                     # Small numerical tolerance matches the mass-closure residual.
                     "launch_compatible": ev.launch_speed_needed_m_s <= inp.hand_launch_speed_m_s + 1e-3,
                     "pack_envelope_validated": False})
    return rows


def propulsion_checks(d: Design) -> dict:
    """Screen baseline and lighter candidates at min/nominal/full pack voltage.

    Manufacturer mass/KV/voltage evidence is distinct from assumed prop CT/CP.
    A passing scalar calculation never marks a motor as flight validated.
    """
    from .aero.polar import FixedWingAero
    from . import propulsion as prop
    from .sizing import cruise_speed

    cfg = d.design["propulsion"]
    screen = cfg["screening"]
    inp = inputs_for(d)
    pack = d.electronics.pack
    rows = []
    for candidate in screen["candidates"]:
        delta_mass = candidate["mass_g"] - d.electronics.propulsion_masses_g["motor"]
        auw = d.selected.auw_kg + delta_mass * (1 + inp.contingency_fraction) / 1000
        ac = FixedWingAero(auw, d.selected.wing_area_m2, d.selected.polar, d.rho)
        speed = cruise_speed(ac, d.survey_speed_limit_m_s)
        shaft = prop.cruise_shaft_power_w(float(ac.drag_n(speed)), speed, inp.prop_efficiency)
        cruise_power = prop.electrical_power_w(shaft, inp.motor_efficiency, inp.esc_efficiency)
        cruise_power += inp.avionics_power_w + inp.payload_power_w
        for state, voltage in (("minimum", pack.min_v), ("nominal", pack.nominal_v), ("full", pack.max_v)):
            check = propeller_check(
                auw_kg=auw, diameter_in=cfg["prop_diameter_in"], motor_kv=candidate["motor_kv"],
                voltage_v=voltage, rho=d.rho, ct=screen["ct"], cp=screen["cp"],
                loaded_rpm_fraction=screen["loaded_rpm_fraction"],
                required_static_tw=d.design["requirements"]["launch_static_thrust_to_weight"],
                esc_rating_a=screen["esc_rating_a"], cruise_electrical_power_w=cruise_power,
                motor_efficiency=cfg["motor_efficiency"], esc_efficiency=cfg["esc_efficiency"],
                current_headroom=screen["current_headroom"],
            )
            rows.append({"candidate": candidate["name"], "source": candidate["source"],
                         "motor_mass_g": candidate["mass_g"], "auw_kg": auw,
                         "voltage_state": state,
                         "pack_compatible": pack.series <= candidate["max_cells_series"],
                         "motor_15s_power_pass": check["full_throttle_electrical_power_w"] <= candidate["max_15s_power_w"],
                         "continuous_thermal_validated": False, **check})
    return {"assumptions": {k: v for k, v in screen.items() if k != "candidates"},
            "checks": rows, "status": "candidate screening; no measured 13x8 thrust/current curve"}


def thermal_report(d: Design) -> dict:
    """Orin inlet energy balance at the design cruise airspeed."""
    return cooling_airflow(rho=d.rho, inlet_speed_m_s=d.selected.cruise_speed_m_s,
                           **d.design["thermal"])


def balance_alternatives(d: Design, balance: dict) -> list[dict]:
    """Compare cage shift and 7% SM using the exported physical mass moment.

    Geometry and holes must be regenerated for any adopted cage shift. The
    unchanged component masses make this a moment/trim trade, not a CAD release.
    """
    from .fab.geometry import WingGeometry, spar_layout

    fab = yaml.safe_load((d.platform_dir / "fabrication.yaml").read_text())
    trade = d.design["balance_trades"]
    pl = d.design["planform"]
    wing = WingGeometry.from_airframe(airframe_geometry(d))
    spars = spar_layout(wing, d.design["structure"]["spars"], pl["pod_width_mm"] / 2)
    lug_front = float(spars.joiner.p0[0]) - trade["joiner_lug_forward_offset_mm"]
    cage_x = fab["layout"]["cage_lens_axis_x_mm"]
    cage_mass = d.payloads[d.design["payload"]["size_for"]].cage_mass_g
    if "contingency_g" not in balance:
        raise ValueError("Balance alternatives require manifest balance.contingency_g; rebuild parts")
    real_mass = balance["auw_g"] - balance["contingency_g"]
    pack_mass = d.electronics.pack.mass_g
    rows = []
    for name, shift, target in (("shift cage aft", trade["cage_shift_mm"], pl["static_margin"]),
                                ("accept 7% static margin", 0.0, trade["alternative_static_margin"])):
        twist, stability = stab.solve_washout(
            d.wing, pl["airfoil_root"], pl["airfoil_tip"], d.selected.summary()["cl_cruise"],
            target, pod=(pl["pod_length_mm"], pl["pod_width_mm"]),
            blend_start_mm=pl["pod_width_mm"] / 2)
        target_cg = stability.x_np_mm - target * stability.mac_mm
        shifted_cg = balance["cg_x_mm"] + cage_mass * shift / real_mass
        battery_required = balance["battery_x_mm"] + (target_cg - shifted_cg) * real_mass / pack_mass
        positions = [min(max(battery_required, low), high)
                     for low, high in fab["layout"]["battery_bays_mm"]]
        battery_x = min(positions, key=lambda x: abs(x - battery_required))
        actual_cg = shifted_cg + pack_mass * (battery_x - balance["battery_x_mm"]) / real_mass
        clearance = lug_front - (cage_x + shift + trade["cage_half_length_mm"])
        rows.append({"alternative": name, "cage_lens_axis_x_mm": cage_x + shift,
                     "cage_lug_clearance_mm": clearance,
                     "cage_clearance_pass": clearance >= trade["min_cage_lug_clearance_mm"],
                     "target_static_margin": target, "washout_deg": twist,
                     "battery_required_x_mm": battery_required, "battery_x_mm": battery_x,
                     "battery_target_reachable": math.isclose(battery_x, battery_required, abs_tol=1e-6),
                     "cg_x_mm": actual_cg, "static_margin": (stability.x_np_mm - actual_cg) / stability.mac_mm,
                     "mechanical_rebuild_required": True})
    return rows
