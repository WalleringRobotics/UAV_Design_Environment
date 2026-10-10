"""Fabrication: geometry (no CAD kernel) and the full CAD build (needs cadquery)."""

from pathlib import Path

import numpy as np
import pytest
import yaml

from uavdesign import design as D
from uavdesign.fab.geometry import PodGeometry, WingGeometry, spar_layout
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


# ---- full CAD build (slow) ------------------------------------------------

cq = pytest.importorskip("cadquery")


@pytest.mark.cad
def test_full_build_prints_and_balances():
    from uavdesign.fab.build import build

    r = build()
    assert r.all_fit, [bp.name for bp in r.parts if not bp.fit.fits]
    for bp in r.parts:
        assert bp.part.solid.isValid(), bp.name
        assert len(bp.part.solid.Solids()) == 1, bp.name
        assert bp.mass.mass_g > 1.0, bp.name
    names = {bp.name for bp in r.parts}
    assert {"survey_cage", "spar_box", "pod_mid", "fin_L", "fin_R"} <= names
    assert 0.04 <= r.balance.static_margin <= 0.10
    # analytic sizing (with CAD calibration) and CAD balance agree on AUW
    assert r.balance.auw_g == pytest.approx(r.design.selected.auw_kg * 1000, rel=0.05)
