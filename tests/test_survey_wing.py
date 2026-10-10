"""Survey wing: requirements -> payload -> electronics -> sizing -> stability."""

from pathlib import Path

import numpy as np
import pytest

from uavdesign import design as D
from uavdesign import survey as sv
from uavdesign.aero import stability as st
from uavdesign.aero.airfoil import section_polar, summarize
from uavdesign.electronics import Electronics
from uavdesign.payload import SurveyPayload
from uavdesign.sizing import spar_set
from uavdesign.structures import Tube, check_spar, servo_torque_kg_cm

ROOT = Path(__file__).resolve().parent.parent
PLAT = ROOT / "platforms" / "survey_wing"


@pytest.fixture(scope="module")
def design():
    return D.run()


# ---- survey geometry (architecture doc §7 numbers) --------------------------

def test_imx542_footprint_matches_architecture_doc():
    cam = sv.Camera(5328, 3040, 2.74, 25.0, 4.0)
    assert cam.gsd_m(100) * 100 == pytest.approx(1.096, abs=0.005)      # ~1.1 cm
    assert cam.swath_m(100) == pytest.approx(58.4, abs=0.1)
    assert cam.footprint_along_m(100) == pytest.approx(33.3, abs=0.1)
    # doc: 1.5 fps gives 80 % forward overlap at 10 m/s
    assert sv.trigger_rate_hz(cam, 100, 10.0, 0.8) == pytest.approx(1.5, abs=0.02)


def test_blur_limit_round_trip():
    cam = sv.Camera(5328, 3040, 2.74, 25.0, 4.0)
    v = sv.max_speed_for_blur(cam, 100, 1 / 2500, 0.6)
    assert sv.blur_px(cam, 100, v, 1 / 2500) == pytest.approx(0.6)


# ---- payload + electronics ----------------------------------------------------

def test_payload_configs():
    heavy = SurveyPayload.from_yaml(ROOT / "payload" / "survey_cage.yaml", "orin")
    light = SurveyPayload.from_yaml(ROOT / "payload" / "survey_cage.yaml", "cm5")
    assert 880 <= heavy.mass_g <= 1140          # architecture doc §7 range
    assert light.mass_g < heavy.mass_g
    assert light.cage_mass_g == heavy.cage_mass_g    # same rigid cage
    assert heavy.power_w > light.power_w


def test_power_tree_within_rail_ratings_and_regulator_headroom():
    e = Electronics.from_yaml(PLAT / "electronics.yaml")
    pl = SurveyPayload.from_yaml(ROOT / "payload" / "survey_cage.yaml", "orin")
    tree = e.power_tree(D.payload_loads_w(pl))
    for name, r in tree.items():
        if name != "pack_total_w" and r["utilisation"] is not None:
            assert r["utilisation"] < 0.8, name
    # 12 V compute buck needs >= 13.3 V in: must hold down to the pack's cut-off
    assert e.pack.min_v >= 13.3
    # sum of rails propagates to the pack with losses
    assert tree["pack_total_w"] > tree["compute_12v"]["total_w"]


def test_open_items_are_listed():
    e = Electronics.from_yaml(PLAT / "electronics.yaml")
    assert any("esc" in s for s in e.open_items())


# ---- airfoil / sizing / stability ------------------------------------------

def test_s5010_section_sane():
    s = summarize("s5010", 3e5)
    assert 1.1 < s.cl_max < 1.4
    assert abs(s.cm_at_cl_design) < 0.02
    assert 0.09 < s.t_over_c < 0.11


def test_design_closes_and_meets_requirements(design):
    sel = design.selected
    assert sel.converged
    assert 2.5 < sel.auw_kg < 4.0
    assert design.evaluations["orin"].endurance_min >= 45
    assert design.evaluations["cm5"].endurance_min > design.evaluations["orin"].endurance_min
    # hand launch: stall at release margin
    req = design.design["requirements"]
    for ev in design.evaluations.values():
        assert ev.launch_speed_needed_m_s <= req["hand_launch_speed_m_s"] + 0.01
    # survey speed limit respected unless stall forces faster
    assert sel.cruise_speed_m_s <= max(design.survey_speed_limit_m_s, 1.3 * sel.stall_speed_m_s) + 1e-6


def test_vlm_neutral_point_close_to_quarter_mac(design):
    w = design.wing
    assert design.stability.x_np_wing_mm == pytest.approx(w.x_ac_mm, rel=0.03)
    assert design.stability.x_np_mm < design.stability.x_np_wing_mm      # pod is destabilising


def test_washout_matches_panknin(design):
    """Independent cross-check of the VLM trim twist (single-airfoil case)."""
    w = design.wing
    tw, _ = st.solve_washout(w, "s5010", "s5010", 0.5, 0.06)
    p = section_polar("s5010", 2.5e5)
    cl, cm, a = p["cl"], p["cm"], p["alpha_deg"]
    a0 = float(np.interp(0, cl[:40], a[:40]))
    cm0 = float(np.interp(0, cl[:40], cm[:40]))
    pk = st.panknin_washout_deg(cm0, cm0, a0, a0, 0.5, 0.06, w.aspect_ratio, w.taper_ratio,
                                w.placed_panels[0].sweep_deg_at(0.25))
    assert tw == pytest.approx(pk, abs=0.5)


def test_spars_have_reserve(design):
    w = design.wing
    W = design.selected.auw_kg * 9.80665
    req = design.design["requirements"]
    sp = design.design["structure"]["spars"]
    joiner = Tube(sp["joiner"]["od_mm"], sp["joiner"]["id_mm"])
    outer = Tube(sp["outer_spar"]["od_mm"], sp["outer_spar"]["id_mm"])
    pod_half = design.design["planform"]["pod_width_mm"] / 2
    assert check_spar(joiner, W, w.half_span_mm, req["load_factor_limit"], req["safety_factor"],
                      pod_half, w.taper_ratio, 0.85).reserve_factor > 1.2
    assert check_spar(outer, W, w.half_span_mm, req["load_factor_limit"], req["safety_factor"],
                      sp["joiner"]["half_length_mm"], w.taper_ratio, 0.85).reserve_factor > 1.2
    tube, frac, fixed = spar_set(sp, design.design["planform"]["pod_width_mm"])
    assert fixed > 0 and 0 < frac < 1


def test_servo_torque_far_below_rating(design):
    w = design.wing
    e0, e1 = design.design["planform"]["elevon_span_fraction"]
    chord = float(w.chord_at(0.5 * (e0 + e1) * w.half_span_mm)) * design.design["planform"]["elevon_chord_fraction"]
    tq = servo_torque_kg_cm(chord, (e1 - e0) * w.half_span_mm, 25.0, 20.0, 45.0)
    assert 2 * tq < 2.6      # MKS HV6100 at 6 V, with 2x margin


def test_calibration_is_applied_when_present(design):
    if not (PLAT / "calibration.yaml").exists():
        pytest.skip("no CAD calibration yet")
    raw = D.run(calibration={})
    assert design.selected.auw_kg != pytest.approx(raw.selected.auw_kg)
