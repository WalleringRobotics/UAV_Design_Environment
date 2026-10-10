import math

import numpy as np
import pytest

from uavdesign.aero import DragPolar, FixedWingAero
from uavdesign.aero import constraint as con
from uavdesign.atmosphere import G, RHO0, isa_density, wing_loading_g_dm2


@pytest.fixture
def polar():
    return DragPolar.from_oswald(cd0=0.025, aspect_ratio=3.665, oswald_e=0.8, cl_max=0.7)


def test_calculator_stall_speed_reproduced():
    """Calculator: 900 g, 13.37 dm^2, CLmax 1.0 -> 37 km/h at sea level."""
    p = DragPolar(cd0=0.02, k=0.1, cl_max=1.0)
    ac = FixedWingAero(0.9, 0.1337, p, RHO0)
    assert ac.stall_speed() * 3.6 == pytest.approx(37, abs=0.5)
    assert wing_loading_g_dm2(ac.wing_loading_n_m2) == pytest.approx(67, abs=0.5)


def test_optimum_speeds_ordering_and_ld(polar):
    ac = FixedWingAero(0.9, 0.1337, polar, isa_density(500))
    assert ac.v_min_power < ac.v_max_ld  # always: v_mp = 0.76 * v_md
    assert ac.v_min_power / ac.v_max_ld == pytest.approx(3 ** -0.25)
    v = np.linspace(8, 40, 4001)
    ld = ac.lift_to_drag(v)
    assert ld.max() == pytest.approx(polar.ld_max, rel=1e-4)
    assert v[np.argmax(ld)] == pytest.approx(ac.v_max_ld, abs=0.02)
    p = ac.aero_power_w(v)
    assert v[np.argmin(p)] == pytest.approx(ac.v_min_power, abs=0.02)


def test_baseline_wing_is_stall_limited_for_endurance(polar):
    """With a reflexed-section CLmax of 0.7 the min-power CL (~0.83) is unreachable."""
    ac = FixedWingAero(0.9, 0.1337, polar, isa_density(500))
    assert polar.cl_min_power > polar.cl_max
    assert ac.stall_limited()["v_min_power"]


def test_level_flight_drag_equals_weight_over_ld(polar):
    ac = FixedWingAero(0.9, 0.1337, polar, isa_density(500))
    v = 16.0
    assert ac.drag_n(v) == pytest.approx(ac.weight_n / ac.lift_to_drag(v))


def test_cruise_constraint_matches_drag_over_weight(polar):
    rho = isa_density(500)
    ac = FixedWingAero(0.9, 0.1337, polar, rho)
    v = 16.0
    tw = con.cruise_tw(ac.wing_loading_n_m2, rho, v, polar.cd0, polar.k)
    assert tw == pytest.approx(ac.drag_n(v) / ac.weight_n)


def test_turn_at_zero_bank_is_cruise(polar):
    rho, v, ws = 1.2, 15.0, 70.0
    assert con.turn_tw(ws, rho, v, polar.cd0, polar.k, 0.0) == pytest.approx(
        con.cruise_tw(ws, rho, v, polar.cd0, polar.k)
    )


def test_stall_and_launch_lines():
    rho, cl = 1.2, 0.7
    ws = con.stall_ws_max(rho, 12.0, cl)
    p = DragPolar(0.02, 0.1, cl)
    ac = FixedWingAero(ws * 0.1 / G, 0.1, p, rho)  # mass chosen to hit that W/S
    assert ac.stall_speed() == pytest.approx(12.0)
    assert con.launch_ws_max(rho, 12.0 * 1.2, cl, margin=1.2) == pytest.approx(ws)


def test_power_per_mass_units():
    # T/W 0.1 at 15 m/s with eta 0.6 -> 0.1*15*9.80665/0.6 W/kg
    assert con.power_per_mass_w_kg(0.1, 15.0, 0.6) == pytest.approx(0.1 * 15 * G / 0.6)


def test_isa_density_reference_points():
    assert isa_density(0) == pytest.approx(1.225, abs=1e-3)
    assert isa_density(500) == pytest.approx(1.1673, abs=1e-3)
    assert isa_density(500, 15) < isa_density(500)
    assert np.allclose(isa_density(np.array([0.0, 500.0])), [isa_density(0), isa_density(500)])
