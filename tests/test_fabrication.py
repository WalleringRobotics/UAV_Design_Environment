"""Fabrication: geometry (no CAD kernel) and the full CAD build (needs cadquery)."""

from pathlib import Path

import numpy as np
import pytest
import yaml

from uavdesign import design as D
from uavdesign.fab.geometry import (PodGeometry, WingGeometry, spar_layout,
                                    battery_envelope_fits, cage_mount_datums, hatch_magnet_datums)
from uavdesign.fab.printer import PrinterProfile, check_fit

ROOT = Path(__file__).resolve().parent.parent
FAB = yaml.safe_load((ROOT / "platforms" / "survey_wing" / "fabrication.yaml").read_text())
PRINTER = PrinterProfile.from_dict(FAB["printer"])


@pytest.fixture(scope="module")
def geom():
    d = D.run(solve_stability=False)
    g = D.airframe_geometry(d)
    w = WingGeometry.from_airframe(g, FAB["wing"]["te_thickness_mm"])
    return d, g, w


def _signed_area(xz):
    x, z = xz[:, 0], xz[:, 1]
    return 0.5 * np.sum(x * np.roll(z, -1) - np.roll(x, -1) * z)


def _self_intersects(poly):
    """O(n^2) segment test — fine for ~180-point sections."""
    n = len(poly)

    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        for j in range(i + 2, n):
            if (j + 1) % n == i:
                continue
            c, d = poly[j], poly[(j + 1) % n]
            if ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d):
                return True
    return False


def test_core_one_plus_volume():
    assert (PRINTER.bed_x_mm, PRINTER.bed_y_mm, PRINTER.max_z_mm) == (250, 220, 270)


def test_fit_check_basic():
    bar = np.array([[x, y, z] for x in (0, 290) for y in (0, 12) for z in (0, 100)], float)
    f = check_fit(bar, PRINTER)
    assert f.fits and 25 < f.angle_deg < 65          # 290 mm > 240 usable: only fits diagonally
    wide = bar * [1.0, 3.5, 1.0]
    assert not check_fit(wide, PRINTER).fits          # 290 x 42 overflows even on the diagonal
    tall = bar * [0.1, 1, 3]
    assert not check_fit(tall, PRINTER).fits          # 300 mm tall > 270 mm


def test_sections_are_simple_polygons_with_printable_te(geom):
    _, _, w = geom
    for y in (0.0, w.blend_start_mm, 0.5 * w.half_span_mm, w.half_span_mm):
        s = w.section(y)
        xz = s[:, [0, 2]]
        assert abs(_signed_area(xz)) > 100
        assert not _self_intersects(xz)
        assert np.linalg.norm(s[0] - s[-1]) == pytest.approx(w.te_thickness_mm, abs=0.15)


def test_washout_rotates_tip_nose_down(geom):
    _, g, w = geom
    tip = w.section(w.half_span_mm)
    i_le = np.argmin(tip[:, 0])
    te_z = 0.5 * (tip[0, 2] + tip[-1, 2])
    assert te_z > tip[i_le, 2] if g["washout_deg"] > 0 else True


def test_spar_layout_inside_the_wing(geom):
    _, g, w = geom
    sl = spar_layout(w, g["spars"], g["pod_width_mm"] / 2)
    assert all(c["ok"] for c in sl.checks.values()), sl.checks
    assert sl.joiner.p0[1] == -sl.joiner.p1[1]
    # joiner sits between 15 % and 60 % chord along its whole length
    for y in np.linspace(0, sl.joiner.p1[1], 10):
        xc = w.x_over_c_of(y, sl.joiner.p0[0])
        assert 0.15 <= xc <= 0.60


def test_pod_contains_cage_and_prop_clears_wing(geom):
    d, g, w = geom
    pod = PodGeometry.from_dict(FAB["pod"])
    pl = d.payloads["orin"]
    xcam = FAB["layout"]["cage_lens_axis_x_mm"]
    inner_h = pod.top_z(xcam) - pod.bottom_z(xcam) - 2 * FAB["pod"]["wall_mm"]
    lens_to_rx = pl.cage_members["gnss_receiver"]["position_mm"][2] + pl.cage_members["gnss_receiver"]["envelope_mm"][2]
    assert lens_to_rx + pl.window_standoff_mm < inner_h
    r_prop = g["prop_diameter_in"] * 25.4 / 2
    te_at_tip = float(w.le_x(r_prop) + w.chord(r_prop))
    prop_plane = FAB["layout"]["positions"]["propeller"][0]
    assert prop_plane - te_at_tip > 40


def test_battery_bays_use_real_envelopes_instead_of_unrestricted_cg_ranges():
    pod = PodGeometry.from_dict(FAB["pod"])
    for bay in FAB["layout"]["battery_placements"]:
        for x in np.linspace(*bay["cg_range_mm"], 31):
            assert battery_envelope_fits(pod, x, bay["center_z_mm"], bay["size_mm"]), (bay["name"], x)
    assert not battery_envelope_fits(pod, 290, -60, (70, 108, 22))
    assert not battery_envelope_fits(pod, -110, -60, (70, 108, 22))


def test_shared_cage_and_hatch_datums():
    pod = PodGeometry.from_dict(FAB["pod"])
    datum = cage_mount_datums(pod, FAB["layout"], FAB["pod"]["wall_mm"], 6.0)
    assert len(set(datum["hole_xy_mm"])) == 4
    assert datum["base_z_mm"] - datum["ledge_top_z_mm"] == pytest.approx(5.0)
    for i in range(len(FAB["pod"]["hatches_x_mm"])):
        axes = hatch_magnet_datums(pod, FAB["pod"], i)
        assert len(set(axes)) == 4


# ---- full CAD build (slow) ------------------------------------------------

@pytest.fixture(scope="module")
def built():
    pytest.importorskip("cadquery")
    from OCP.OSD import OSD_ThreadPool
    from uavdesign.fab.build import build

    OSD_ThreadPool.DefaultPool_s().Init(1)
    return build()


@pytest.mark.cad
def test_full_build_prints_and_balances(built):
    r = built
    assert r.all_fit, [bp.name for bp in r.parts if not bp.fit.fits]
    for bp in r.parts:
        assert bp.part.solid.isValid(), bp.name
        assert len(bp.part.solid.Solids()) == 1, bp.name
        assert bp.mass.mass_g > 0.1, bp.name
    names = {bp.name for bp in r.parts}
    assert {"survey_cage", "spar_box", "pod_mid", "fin_L", "fin_R"} <= names
    assert 0.04 <= r.balance.static_margin <= 0.10
    # analytic sizing (with CAD calibration) and CAD balance agree on AUW
    assert r.balance.auw_g == pytest.approx(r.design.selected.auw_kg * 1000, rel=0.01)


_CLASSIFIERS = {}


def _inside(part, point):
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON

    key = id(part)
    if key not in _CLASSIFIERS:
        _CLASSIFIERS[key] = (part, [(s.BoundingBox(), BRepClass3d_SolidClassifier(s.wrapped))
                                    for s in part.Solids()])
    x, y, z = map(float, point)
    for bounds, classifier in _CLASSIFIERS[key][1]:
        if not (bounds.xmin <= x <= bounds.xmax and bounds.ymin <= y <= bounds.ymax
                and bounds.zmin <= z <= bounds.zmax):
            continue
        classifier.Perform(gp_Pnt(x, y, z), 1e-5)
        if classifier.State() in (TopAbs_IN, TopAbs_ON):
            return True
    return False


@pytest.mark.cad
def test_cage_damper_holes_are_coaxial_with_pod_ledges(built):
    parts = {bp.name: bp.part.solid for bp in built.parts}
    pod = PodGeometry.from_dict(built.fab["pod"])
    datum = cage_mount_datums(pod, built.fab["layout"], built.fab["pod"]["wall_mm"],
                             built.design.payloads["orin"].window_standoff_mm)
    for x, y in datum["hole_xy_mm"]:
        for name, z in (("survey_cage", datum["base_z_mm"] + 2),
                        ("pod_mid", datum["ledge_top_z_mm"] - 2)):
            assert not _inside(parts[name], (x, y, z)), name
            assert _inside(parts[name], (x + 5.3, y, z)), name


@pytest.mark.cad
def test_magnet_pockets_exist_on_both_mating_parts(built):
    parts = {bp.name: bp.part.solid for bp in built.parts}
    pod = PodGeometry.from_dict(built.fab["pod"])
    z = built.fab["pod"]["hatch_z_above_mm"]
    body = [parts[k] for k in ("pod_nose", "pod_mid", "pod_tail")]
    for i, name in enumerate(built.fab["pod"]["hatch_names"]):
        hatch = parts[f"hatch_{name}"]
        for x, y in hatch_magnet_datums(pod, built.fab["pod"], i):
            assert not any(_inside(s, (x, y, z - 1)) for s in body)
            assert any(_inside(s, (x + 4.2, y, z - 1)) for s in body)
            assert not _inside(hatch, (x, y, z + 1))
            assert _inside(hatch, (x + 4.2, y, z + 1))


@pytest.mark.cad
def test_motor_mount_has_continuous_straight_sided_slots(built):
    tail = next(bp.part.solid for bp in built.parts if bp.name == "pod_tail")
    xf = built.fab["pod"]["firewall_x_mm"]
    r0, r1 = built.fab["pod"]["motor_slot_r_mm"]
    for angle in np.radians([45, 135, 225, 315]):
        along = np.array([np.cos(angle), np.sin(angle)])
        across = np.array([-along[1], along[0]])
        for radius in np.linspace(r0, r1, 11):
            for offset in (-1.60, 0, 1.60):
                yz = radius * along + offset * across
                assert not _inside(tail, (xf - 2, *yz))
        yz = ((r0 + r1) / 2) * along + 2.0 * across
        assert _inside(tail, (xf - 2, *yz))


@pytest.mark.cad
def test_new_access_retention_and_optional_hook_parts(built):
    from uavdesign.fab.parts import build_launch_hook
    from uavdesign.fab.build import _vertices

    names = {bp.name for bp in built.parts}
    assert {"servo_cover_L", "servo_cover_R", "battery_tray_forward", "battery_tray_aft",
            "cooling_duct_1", "cooling_duct_2", "cooling_duct_3"} <= names
    assert "launch_hook_optional" not in names
    pod = PodGeometry.from_dict(built.fab["pod"])
    hook = build_launch_hook(pod, built.balance.cg_x_mm, built.fab["pod"]["wall_mm"])
    assert hook.solid.isValid() and len(hook.solid.Solids()) == 1
    assert check_fit(_vertices(hook.solid), PRINTER, hook.print_up).fits


@pytest.mark.cad
def test_cooling_route_clears_both_real_battery_envelopes(built):
    from uavdesign.fab.parts import box
    from uavdesign.fab.massprops import volume_props

    ducts = [bp.part.solid for bp in built.parts if bp.name.startswith("cooling_duct_")]
    tray = next(bp.part.solid for bp in built.parts if bp.name == "avionics_tray")
    assert all(volume_props(duct.intersect(tray))[0] < 1e-5 for duct in ducts)
    shells = [bp.part.solid for bp in built.parts if bp.name in ("pod_nose", "pod_mid", "pod_tail")]
    retainers = [bp.part.solid for bp in built.parts if bp.name.startswith("battery_tray_")]
    assert all(volume_props(retainer.intersect(shell))[0] < 1e-5
               for retainer in retainers for shell in shells)
    for bay in built.fab["layout"]["battery_placements"]:
        length, width, height = bay["size_mm"]
        z = bay["center_z_mm"]
        for x in np.linspace(*bay["cg_range_mm"], 5):
            pack = box(x - length / 2, x + length / 2, -width / 2, width / 2, z - height / 2, z + height / 2)
            assert all(volume_props(duct.intersect(pack))[0] < 1e-5 for duct in ducts)


@pytest.mark.cad
def test_wing_dowels_and_horn_pads_exist_on_both_sides(built):
    from uavdesign.fab.massprops import volume_props

    g = D.airframe_geometry(built.design)
    w = WingGeometry.from_airframe(g, built.fab["wing"]["te_thickness_mm"])
    root = g["pod_width_mm"] / 2
    count = int(np.ceil((w.half_span_mm - root) / built.fab["wing"]["max_segment_span_mm"]))
    stations = np.linspace(root, w.half_span_mm, count + 1)
    e0, e1 = g["elevon_y_mm"]
    ys = e0 + 0.25 * (e1 - e0)
    hp = w.point_at(ys, 1 - g["elevon_chord_fraction"] + 0.09, "upper")
    for side, sign in (("R", 1), ("L", -1)):
        wings = [bp.part.solid for bp in built.parts if bp.name.startswith("wing_seg") and f"_{side}" in bp.name]
        for station in stations[1:-1]:
            for xc in (0.18, 0.60):
                p = w.point_at(float(station), xc)
                for dy in (-4, 4):
                    point = (p[0], sign * (p[1] + dy), p[2])
                    rim = (p[0], sign * (p[1] + dy), p[2] + 2.5)
                    assert not any(_inside(s, point) for s in wings)
                    assert any(_inside(s, rim) for s in wings), (side, float(station), xc, dy, p.tolist())
        for i, (ya, yb) in enumerate(zip(stations[:-1], stations[1:]), 1):
            split = [bp.part.solid for bp in built.parts if bp.name.startswith(f"wing_seg{i}_{side}_")]
            if not split:
                continue
            assert len(split) == 2
            xc = built.fab["wing"]["chordwise_split_x_over_c"]
            pa, pb = w.point_at(float(ya), xc), w.point_at(float(yb), xc)
            tangent = pb - pa
            normal = np.array([tangent[1], -tangent[0], 0.0])
            normal /= np.linalg.norm(normal)
            for fraction in (0.50, 0.80):
                center = w.point_at(float(ya + fraction * (yb - ya)), xc)
                for direction in (-1, 1):
                    point = center + direction * normal * 4
                    point[1] *= sign
                    assert not any(_inside(s, point) for s in split)
                    assert any(_inside(s, point + [0, 0, 2.5]) for s in split), (side, i, fraction, direction, point)
        cover = next(bp.part.solid for bp in built.parts if bp.name == f"servo_cover_{side}")
        assert all(volume_props(cover.intersect(wing))[0] < 1e-4 for wing in wings)
        elevon = next(bp.part.solid for bp in built.parts if bp.name == f"elevon1_{side}")
        assert _inside(elevon, (hp[0], sign * ys, hp[2] + 2))
        for dx in (-4, 4):
            assert not _inside(elevon, (hp[0] + dx, sign * ys, hp[2] + 2))
