"""Wing geometry / static margin.

The reference values are the outputs of the rcplanes.online flying-wing CG
calculator for the baseline planform (root 275, tip 107, half span 350,
LE sweep 217 mm, static margin 6 %). The calculator rounds to 0.01, so the
tolerances are set to that.
"""

import math

import pytest

from uavdesign.aero import Panel, Wing

CALC = {
    "inputs": dict(root=275.0, tip=107.0, half_span=350.0, sweep_mm=217.0, sm=0.06),
    "mac_mm": 203.31,
    "x_le_mac_mm": 92.59,      # "Sweep distance at MAC (C)"
    "y_mac_mm": 149.35,        # "From root chord to MAC (d)"
    "x_ac_mm": 143.42,         # "From wing root LE to AC"
    "x_cg_mm": 131.22,         # "From wing root LE to CG"
    "area_mm2": 133700.0,
    "aspect_ratio": 3.66,
    "sweep_deg": 31.8,
}


@pytest.fixture
def wing() -> Wing:
    i = CALC["inputs"]
    return Wing.trapezoidal(i["root"], i["tip"], i["half_span"], le_sweep_mm=i["sweep_mm"])


def test_matches_rcplanes_calculator(wing):
    assert wing.mac_mm == pytest.approx(CALC["mac_mm"], abs=0.01)
    assert wing.x_le_mac_mm == pytest.approx(CALC["x_le_mac_mm"], abs=0.01)
    assert wing.y_mac_mm == pytest.approx(CALC["y_mac_mm"], abs=0.01)
    assert wing.x_ac_mm == pytest.approx(CALC["x_ac_mm"], abs=0.01)
    assert wing.cg_for_static_margin(CALC["inputs"]["sm"]) == pytest.approx(
        CALC["x_cg_mm"], abs=0.01
    )
    assert wing.area_mm2 == pytest.approx(CALC["area_mm2"])
    assert wing.aspect_ratio == pytest.approx(CALC["aspect_ratio"], abs=0.005)
    assert wing.placed_panels[0].le_sweep_deg == pytest.approx(CALC["sweep_deg"], abs=0.05)


def test_sweep_angle_and_distance_are_equivalent():
    a = Wing.trapezoidal(275, 107, 350, le_sweep_mm=217)
    b = Wing.trapezoidal(275, 107, 350, le_sweep_deg=math.degrees(math.atan(217 / 350)))
    assert a.mac_mm == pytest.approx(b.mac_mm)
    assert a.x_ac_mm == pytest.approx(b.x_ac_mm)


def test_static_margin_round_trip(wing):
    for sm in (0.01, 0.06, 0.10):
        assert wing.static_margin(wing.cg_for_static_margin(sm)) == pytest.approx(sm)


@pytest.mark.parametrize("split_y", [50.0, 175.0, 300.0])
def test_splitting_a_trapezoid_changes_nothing(wing, split_y):
    """Two coplanar panels describing the same trapezoid must give identical results.

    This is the check that the multi-panel (cranked wing) composition is exact,
    not an approximation.
    """
    cr, ct, b, s = 275.0, 107.0, 350.0, 217.0
    c_split = cr + (ct - cr) * split_y / b
    x_split = s * split_y / b
    two = Wing([
        Panel(cr, c_split, split_y, x_split),
        Panel(c_split, ct, b - split_y, s - x_split),
    ])
    for attr in ("area_mm2", "mac_mm", "y_mac_mm", "x_le_mac_mm", "x_ac_mm", "aspect_ratio"):
        assert getattr(two, attr) == pytest.approx(getattr(wing, attr), rel=1e-12), attr


def test_rectangular_wing_closed_form():
    w = Wing.trapezoidal(200, 200, 500, le_sweep_mm=0)
    assert w.mac_mm == pytest.approx(200)
    assert w.y_mac_mm == pytest.approx(250)
    assert w.x_ac_mm == pytest.approx(50)
    assert w.aspect_ratio == pytest.approx(5.0)


def test_cranked_wing_from_dict():
    spec = {
        "panels": [
            {"root_chord_mm": 300, "tip_chord_mm": 200, "span_mm": 100, "le_sweep_mm": 80},
            {"root_chord_mm": 200, "tip_chord_mm": 100, "span_mm": 300, "le_sweep_mm": 150},
        ]
    }
    w = Wing.from_dict(spec)
    assert w.half_span_mm == 400
    assert w.area_mm2 == pytest.approx(2 * (250 * 100 + 150 * 300))
    # MAC lies between the panel MACs, AC aft of the inboard panel's AC
    p1, p2 = w.placed_panels
    assert min(p1.mac_mm, p2.mac_mm) < w.mac_mm < max(p1.mac_mm, p2.mac_mm)
    assert p2.root_le_x_mm == 80 and p2.root_y_mm == 100


def test_mismatched_panel_chords_rejected():
    with pytest.raises(ValueError):
        Wing([Panel(300, 200, 100, 0), Panel(190, 100, 200, 0)])


def test_planform_helpers(wing):
    assert wing.chord_at(0) == pytest.approx(275)
    assert wing.chord_at(350) == pytest.approx(107)
    assert wing.le_x_at(-350) == pytest.approx(217)  # symmetric
    y, x = wing.outline()
    assert y[0] == 0 and x[0] == 0 and y[-1] == 0 and x[-1] == 0
    # area centroid sits between root LE and root TE
    assert 0 < wing.planform_centroid_x_mm() < 275
