"""Physical regressions: losses, pack mass, thermal flow and candidate limits."""

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from uavdesign import design as D
from uavdesign.atmosphere import G, isa_density
from uavdesign.electronics import Electronics
from uavdesign.endurance import Battery, MissionSegment, endurance_min
from uavdesign.power import cooling_airflow
from uavdesign.propulsion import propeller_check, static_propeller_point
from uavdesign.sizing import size

ROOT = Path(__file__).resolve().parent.parent
PLAT = ROOT / "platforms/survey_wing"


@pytest.fixture(scope="module")
def design():
    return D.run(solve_stability=False)


def test_hot_day_density_uses_same_pressure():
    cold, hot = isa_density(500), isa_density(500, 15)
    standard_k = 288.15 - 0.0065 * 500
    assert hot / cold == pytest.approx(standard_k / (standard_k + 15))
    assert hot < cold
    with pytest.raises(ValueError):
        isa_density(12000)


def test_pack_rejects_fractional_cells():
    spec = yaml.safe_load((PLAT / "electronics.yaml").read_text())
    spec["pack"]["parallel"] = 1.5
    with pytest.raises(ValueError, match="positive integer"):
        Electronics(spec)


def test_usb_load_propagates_through_both_converters():
    e = Electronics.from_yaml(PLAT / "electronics.yaml")
    a = e.power_tree({})
    b = e.power_tree({"gnss_receiver": 0.9})
    assert b["compute_usb"]["direct_w"] - a["compute_usb"]["direct_w"] == pytest.approx(0.9)
    assert b["compute_12v"]["total_w"] - a["compute_12v"]["total_w"] == pytest.approx(1.0)
    assert b["pack_total_w"] - a["pack_total_w"] == pytest.approx(0.9 / 0.9 / 0.9)


def test_peak_servo_demand_is_not_average_demand():
    e = Electronics.from_yaml(PLAT / "electronics.yaml")
    normal, peak = e.power_tree({}), e.power_tree({}, peak=True)
    assert peak["servo_6v"]["current_a"] == pytest.approx(2)
    assert peak["pack_total_w"] - normal["pack_total_w"] == pytest.approx(11 / 0.88)


def test_power_tree_rejects_cycle_and_negative_load():
    spec = yaml.safe_load((PLAT / "electronics.yaml").read_text())
    spec["rails"]["compute_usb"]["from"] = "compute_usb"
    with pytest.raises(ValueError, match="Cycle"):
        Electronics(spec).power_tree({})
    e = Electronics.from_yaml(PLAT / "electronics.yaml")
    with pytest.raises(ValueError):
        e.power_tree({"compute": -1})


def test_unverified_bom_never_disappears_from_open_items():
    e = Electronics.from_yaml(PLAT / "electronics.yaml")
    assert any("rc_receiver" in item for item in e.open_items())
    assert next(r for r in e.bom_rows() if r["item"] == "motor")["source"]


def test_static_propeller_scaling_and_electrical_losses():
    a = static_propeller_point(13, 6000, 18, 1.1, .11, .055)
    b = static_propeller_point(13, 12000, 18, 1.1, .11, .055)
    assert b.thrust_n / a.thrust_n == pytest.approx(4)
    assert b.shaft_power_w / a.shaft_power_w == pytest.approx(8)
    assert a.electrical_power_w == pytest.approx(a.shaft_power_w / .82 / .95)
    assert a.electrical_power_w > a.shaft_power_w


def test_esc_headroom_changes_pass_flag():
    kwargs = dict(auw_kg=3.4, diameter_in=13, motor_kv=500, voltage_v=21,
                  rho=1.1, ct=.11, cp=.055, loaded_rpm_fraction=.8,
                  required_static_tw=.6, esc_rating_a=40, cruise_electrical_power_w=90)
    assert propeller_check(**kwargs, current_headroom=0)["esc_pass"]
    assert not propeller_check(**kwargs, current_headroom=.2)["esc_pass"]


def test_cooling_flow_closes_energy_balance():
    result = cooling_airflow(20, 15, 1.1, 13.5, .5)
    assert result["mass_flow_kg_s"] * 1005 * 15 == pytest.approx(20)
    assert result["volume_flow_l_s"] == pytest.approx(1.206, rel=.001)
    assert result["inlet_area_mm2"] > 0
    with pytest.raises(ValueError):
        cooling_airflow(20, 15, 1.1, 0)


def test_endurance_rejects_impossible_inputs():
    for kwargs in ({"capacity_ah": -1}, {"capacity_ah": 1, "usable_fraction": 1.1},
                   {"capacity_ah": 1, "peukert_exponent": .5}):
        with pytest.raises(ValueError):
            Battery(**kwargs)
    with pytest.raises(ValueError):
        endurance_min(Battery(5), -1)
    with pytest.raises(ValueError):
        MissionSegment("negative duration", -1, 30)


def test_sizing_uses_design_density_in_trim_cl(design):
    r = design.selected
    expected = 2 * r.auw_kg * G / (design.rho * r.cruise_speed_m_s ** 2 * r.wing_area_m2)
    assert r.summary()["cl_cruise"] == pytest.approx(expected)
    assert sum(r.masses_g.values()) / 1000 == pytest.approx(r.auw_kg)


def test_pack_trade_reflies_mass_and_reports_launch_limit(design):
    one, two = D.battery_trade(design)
    assert two["mass_g"] == pytest.approx(2 * one["mass_g"])
    assert two["auw_kg"] - one["auw_kg"] == pytest.approx(one["mass_g"] / 1000)
    assert two["cruise_power_w"] > one["cruise_power_w"]
    assert two["endurance_min"] < 2 * one["endurance_min"]
    assert one["launch_compatible"]
    assert not two["launch_compatible"]


def test_bungee_trade_keeps_hand_selected_and_saves_area(design):
    hand, bungee = D.launch_trade(design)
    assert hand["selected"] and not bungee["selected"]
    assert hand["converged"] and bungee["converged"]
    assert bungee["area_saving_fraction"] > 0
    assert bungee["wing_area_m2"] < hand["wing_area_m2"]
    assert design.design["requirements"]["launch"]["selected"] == "hand"


def test_lighter_motor_voltage_conflict_is_reported(design):
    checks = D.propulsion_checks(design)["checks"]
    a30 = [row for row in checks if "A30" in row["candidate"]]
    assert a30 and all(not row["pack_compatible"] for row in a30)
    baseline_full = next(row for row in checks if "A40-10L" in row["candidate"] and row["voltage_state"] == "full")
    assert baseline_full["thrust_pass"]
    assert not baseline_full["esc_pass"]
    assert all(not row["continuous_thermal_validated"] for row in checks)


def test_sizing_rejects_half_specified_fixed_pack(design):
    inp = D.inputs_for(design)
    inp.fixed_battery_mass_g = None
    with pytest.raises(ValueError, match="specified together"):
        size(inp)


def test_free_sizing_reserve_and_peukert_close_target(design):
    inp = D.inputs_for(design, selected=False)
    result = size(inp)
    assert result.converged
    assert result.endurance_min == pytest.approx(inp.endurance_min)


def test_survey_infeasibility_is_explicit(design):
    inp = replace(D.inputs_for(design), survey_speed_m_s=5)
    result = size(inp)
    assert result.converged
    assert result.cruise_speed_m_s > inp.survey_speed_m_s
    assert not result.survey_speed_compatible


def test_basler_candidate_dimensions_match_corrected_part(design):
    camera = design.design["survey"]["camera"]
    assert camera["pixels_across"] == 5320
    assert camera["pixels_along"] == 3032
    assert camera["max_fps"] == 7
    assert "a2a5320-7gcpro" in camera["source"]


def test_balance_trade_respects_physical_pack_intervals(design, monkeypatch):
    # A legacy balance could put the pack at x=40. The new fit-checked forward
    # bay stops at x=35; a trade must never continue using the old x limits.
    monkeypatch.setattr(D.stab, "solve_washout", lambda *args, **kwargs: (0, design.stability))
    balance = {"auw_g": design.selected.auw_kg * 1000,
               "contingency_g": design.selected.masses_g["contingency"],
               "cg_x_mm": design.stability.x_np_mm - .06 * design.stability.mac_mm,
               "battery_x_mm": 40}
    rows = D.balance_alternatives(design, balance)
    fab = yaml.safe_load((PLAT / "fabrication.yaml").read_text())
    placements = {p["name"]: p for p in fab["layout"]["battery_placements"]}
    for row in rows:
        placement = placements[row["battery_bay"]]
        low, high = placement["cg_range_mm"]
        assert low <= row["battery_x_mm"] <= high
        assert row["battery_shell_envelope_pass"]
    assert rows[0]["battery_x_mm"] <= 35


def test_snapshot_detects_additions_changes_and_deletions(tmp_path):
    base = tmp_path / "platforms/survey_wing"
    base.mkdir(parents=True)
    config = base / "design_point.yaml"
    config.write_text("value: 1\n")
    snapshot = D.snapshot_inputs(root=tmp_path)
    D.verify_snapshot(snapshot, root=tmp_path)
    config.write_text("value: 2\n")
    with pytest.raises(RuntimeError, match="design_point.yaml"):
        D.verify_snapshot(snapshot, root=tmp_path)
    D.verify_snapshot(snapshot, root=tmp_path,
                      allow_changed=("platforms/survey_wing/design_point.yaml",))
    config.unlink()
    with pytest.raises(RuntimeError, match="design_point.yaml"):
        D.verify_snapshot(snapshot, root=tmp_path)
    snapshot = D.snapshot_inputs(root=tmp_path)
    (base / "new.yaml").write_text("new: true\n")
    with pytest.raises(RuntimeError, match="new.yaml"):
        D.verify_snapshot(snapshot, root=tmp_path)


def test_survey_wind_uses_groundspeed_for_imaging(design):
    report = D.survey_wind_report(design)
    assert report["worst_case_tailwind_groundspeed_m_s"] == pytest.approx(
        design.selected.cruise_speed_m_s + design.mission["mission"]["max_wind_speed_ms"])
    assert not report["tailwind_imaging_compatible"]
    assert report["headwind_progress_possible"]
