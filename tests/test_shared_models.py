"""Shared models used by both platforms: mass/CG, endurance, propulsion."""

from pathlib import Path

import pytest

from uavdesign import endurance as ed
from uavdesign import propulsion as prop
from uavdesign.mass import MassBudget

ROOT = Path(__file__).resolve().parent.parent


# ---- mass / balance ---------------------------------------------------------

def test_cg_and_battery_solve():
    mb = MassBudget(contingency_fraction=0.1)
    mb.add("a", 100, x_mm=0)
    mb.add("b", 100, x_mm=200)
    assert mb.cg_x_mm() == pytest.approx(100)
    mb.add("battery", 200)
    x = mb.solve_position_for_cg("battery", 50)
    mb.set_position("battery", x)
    assert mb.cg_x_mm() == pytest.approx(50)
    # contingency changes AUW but not CG
    assert mb.auw_g == pytest.approx(440)


def test_cg_requires_positions():
    mb = MassBudget()
    mb.add("a", 100, x_mm=0)
    mb.add("b", 100)
    with pytest.raises(ValueError):
        mb.cg_x_mm()


def test_multirotor_budget_still_loads():
    mb = MassBudget.from_yaml(
        ROOT / "platforms" / "multirotor" / "airframe_params.yaml",
        ROOT / "payload" / "payload_manifest.yaml",
        active_payloads=["global_shutter_rgb"],
    )
    assert "payload:orin_nano" in mb.components_g  # always_on
    assert "payload:global_shutter_rgb" in mb.components_g


def test_unknown_payload_rejected():
    with pytest.raises(KeyError):
        MassBudget.from_yaml(
            ROOT / "platforms" / "multirotor" / "airframe_params.yaml",
            ROOT / "payload" / "payload_manifest.yaml",
            active_payloads=["does_not_exist"],
        )


# ---- endurance ---------------------------------------------------------------

def test_peukert_neutral_at_reference_rate():
    b = ed.Battery(capacity_ah=10, peukert_exponent=1.1, usable_fraction=1.0)
    assert ed.endurance_min(b, 10.0) == pytest.approx(60.0)


def test_low_rate_cruise_gets_peukert_bonus():
    b = ed.Battery(capacity_ah=5, nominal_voltage_v=11.1, peukert_exponent=1.05)
    assert ed.endurance_min(b, 2.5) > ed.endurance_min(b, 2.5, apply_peukert=False)


def test_single_segment_mission_matches_constant_current_endurance():
    b = ed.Battery(capacity_ah=5, nominal_voltage_v=11.1, peukert_exponent=1.08)
    power_w = 30.0
    t_min = ed.endurance_from_power_min(b, power_w)
    seg = [ed.MissionSegment("loiter", t_min * 60, power_w)]
    assert ed.mission_margin(b, seg) == pytest.approx(0.0, abs=1e-9)


def test_multi_segment_mission_margin():
    b = ed.Battery(capacity_ah=5, nominal_voltage_v=11.1)
    segs = [
        ed.MissionSegment("climb", 60, 120.0),
        ed.MissionSegment("cruise", 1800, 35.0),
    ]
    m = ed.mission_margin(b, segs)
    assert 0 < m < 1
    # adding a leg only reduces margin
    assert ed.mission_margin(b, segs + [ed.MissionSegment("rtb", 300, 35.0)]) < m


def test_legacy_aliases():
    b = ed.Battery(capacity_ah=16)
    assert ed.hover_endurance_min(b, 30) == ed.endurance_min(b, 30)
    assert ed.hover_current_from_power(222, 22.2) == pytest.approx(10)


# ---- propulsion --------------------------------------------------------------

def test_cruise_and_electrical_power_chain():
    shaft = prop.cruise_shaft_power_w(drag_n=1.0, airspeed_m_s=15.0, prop_efficiency=0.6)
    assert shaft == pytest.approx(25.0)
    assert prop.electrical_power_w(shaft, 0.8, 0.95) == pytest.approx(25.0 / 0.76)


def test_climb_power_exceeds_cruise():
    assert prop.climb_shaft_power_w(1.0, 15.0, 8.8, 2.0) > prop.cruise_shaft_power_w(1.0, 15.0)


def test_rotor_models_unchanged():
    assert prop.thrust_per_motor(6.0, 6, 2.0) == pytest.approx(6.0 * prop.G * 2 / 6)
    pt = prop.PropulsionPoint(6.5, 6, 18, prop.isa_density(500))
    assert pt.hover_power_total_w == pytest.approx(pt.hover_power_per_motor_w * 6)
