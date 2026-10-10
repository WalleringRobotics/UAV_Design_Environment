"""CadQuery part builders for the printed survey wing.

Every builder returns :class:`Part` objects whose solids are in the aircraft
frame (see :mod:`uavdesign.fab.geometry`), so assembled positions — and
therefore mass and CG — come straight from the parts. ``print_up`` is the
direction that points up on the print bed; the printer fit check and the
STL export both use it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cadquery as cq
import numpy as np

from .geometry import PodGeometry, SparLayout, TubePath, WingGeometry

BIG = 5000.0


@dataclass
class Part:
    name: str
    solid: cq.Shape
    profile: str                  # key into fabrication.yaml `profiles`
    print_up: tuple = (0, 0, 1)
    group: str = "airframe"
    side: str = "C"               # "R", "L" or "C"
    notes: list = field(default_factory=list)

    def mirrored(self) -> "Part":
        name = self.name.replace("_R", "_L") if self.name.endswith("_R") or "_R_" in self.name else self.name + "_L"
        up = (self.print_up[0], -self.print_up[1], self.print_up[2])
        return Part(name, self.solid.mirror("XZ"), self.profile, up, self.group, "L", list(self.notes))


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #

def _wire(points: np.ndarray) -> cq.Wire:
    return cq.Wire.makePolygon([cq.Vector(*map(float, p)) for p in points], close=True)


def _vecs(points: np.ndarray) -> list:
    return [cq.Vector(*map(float, p)) for p in points]


def _spline_wire(points: np.ndarray) -> cq.Wire:
    """Smooth closed section (periodic B-spline) — pod cross-sections."""
    return cq.Wire.assembleEdges([cq.Edge.makeSpline(_vecs(points), periodic=True)])


def _airfoil_wire(points: np.ndarray) -> cq.Wire:
    """Airfoil section: one spline TE(upper) -> LE -> TE(lower) plus a straight TE edge."""
    v = _vecs(points)
    return cq.Wire.assembleEdges([cq.Edge.makeSpline(v), cq.Edge.makeLine(v[-1], v[0])])


def _loft_wires(make, sections, ruled):
    solid = cq.Solid.makeLoft([make(s) for s in sections], ruled)
    if solid.Volume() < 0 or not solid.isValid():
        solid = cq.Solid.makeLoft([make(s[::-1]) for s in sections], ruled)
    if solid.Volume() < 0 or not solid.isValid():
        raise ValueError("loft produced an invalid solid")
    return solid


def loft(sections: list[np.ndarray], ruled: bool = False, kind: str = "airfoil") -> cq.Solid:
    """Loft through closed sections.

    kind='airfoil': spline through the LE + straight TE (sharp-edged airfoils);
    kind='smooth' : periodic spline (pod cross-sections);
    kind='polygon': faceted, exact through the points (fallback).
    Flips winding if OCC builds the solid inside-out.
    """
    make = {"airfoil": _airfoil_wire, "smooth": _spline_wire, "polygon": _wire}[kind]
    try:
        return _loft_wires(make, sections, ruled)
    except Exception:  # noqa: BLE001 — fall back to the robust faceted loft
        if kind == "polygon":
            raise
        return _loft_wires(_wire, sections, ruled)


def halfspace(origin, normal) -> cq.Solid:
    """A huge box occupying the side of the plane that `normal` points into."""
    n = np.asarray(normal, float)
    n = n / np.linalg.norm(n)
    ref = np.array([0, 0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0, 0])
    xd = np.cross(ref, n)
    plane = cq.Plane(origin=tuple(map(float, origin)), xDir=tuple(map(float, xd)), normal=tuple(map(float, n)))
    return cq.Workplane(plane).rect(BIG, BIG).extrude(BIG).val()


def box(x0, x1, y0, y1, z0, z1) -> cq.Solid:
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, cq.Vector(x0, y0, z0))


def cylinder(p0, p1, d: float, extend: float = 0.0) -> cq.Solid:
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    v = p1 - p0
    L = float(np.linalg.norm(v))
    u = v / L
    start = p0 - u * extend
    return cq.Solid.makeCylinder(d / 2, L + 2 * extend, cq.Vector(*start), cq.Vector(*u))


def tube_hole(t: TubePath, clearance: float, extend: float = 0.0) -> cq.Solid:
    return cylinder(t.p0, t.p1, t.od_mm + 2 * clearance, extend)


def _clean(shape: cq.Shape) -> cq.Shape:
    try:
        return shape.clean()
    except Exception:  # noqa: BLE001 — OCC clean occasionally fails on polygon lofts
        return shape


# --------------------------------------------------------------------------- #
# Wing
# --------------------------------------------------------------------------- #

def wing_loft(w: WingGeometry, y0: float, y1: float, n_sections: int = 3) -> cq.Solid:
    ys = np.linspace(y0, y1, max(2, n_sections))
    return loft([w.section(float(y)) for y in ys])


def hinge_line(w: WingGeometry, y0: float, y1: float, x_over_c: float, offset: float = 0.0):
    """Two points on the (straight) hinge line at the upper surface, plus its in-plane normal."""
    p0 = w.point_at(y0, x_over_c, "upper")
    p1 = w.point_at(y1, x_over_c, "upper")
    d = (p1 - p0) / np.linalg.norm(p1 - p0)
    n = np.array([d[1], -d[0], 0.0])        # horizontal normal, points aft for a right wing
    if n[0] < 0:
        n = -n
    n = n / np.linalg.norm(n)
    return p0 + n * offset, p1 + n * offset, n


def build_wing_panel(
    w: WingGeometry,
    spars: SparLayout,
    fab_wing: dict,
    y_root: float,
    elevon_y: tuple[float, float],
    elevon_chord_fraction: float,
    printer_fit,
) -> list[Part]:
    """Right wing panel: printable segments (split chordwise when needed) + elevon pieces."""
    clr = fab_wing["tube_clearance_mm"]
    max_span = fab_wing["max_segment_span_mm"]
    y_tip = w.half_span_mm
    n_seg = int(math.ceil((y_tip - y_root) / max_span))
    stations = np.linspace(y_root, y_tip, n_seg + 1)
    hinge_xc = 1.0 - elevon_chord_fraction
    gap = fab_wing["hinge_gap_mm"]
    e0, e1 = elevon_y

    # Elevon cut-out volume (with gap) and the elevon itself
    h0, h1, n = hinge_line(w, e0, e1, hinge_xc)
    cut_box = box(-BIG, BIG, e0 - gap, e1 + gap, -BIG, BIG)
    behind_gap = halfspace(h0 - n * gap / 2, n)
    elevon_void = cut_box.intersect(behind_gap)

    # Servo pocket (one per side), placed in the inner third of the elevon
    ys_servo = e0 + 0.25 * (e1 - e0)
    sp = fab_wing["servo_pocket_mm"]  # span, thickness, chord
    ps = w.point_at(ys_servo, fab_wing["servo_x_over_c"], "camber")
    servo_pocket = box(ps[0] - sp[2] / 2, ps[0] + sp[2] / 2, ys_servo - sp[0] / 2, ys_servo + sp[0] / 2,
                       ps[2] - sp[1] / 2, ps[2] + BIG)   # opens through the upper skin (hatch)

    # Wire channel from root to servo
    pw0 = w.point_at(y_root, fab_wing["wire_channel_x_over_c"])
    pw1 = w.point_at(ys_servo, fab_wing["wire_channel_x_over_c"])
    wire = cylinder(pw0, pw1, fab_wing["wire_channel_mm"], extend=2.0)

    holes = [
        tube_hole(spars.sleeve, clr, extend=1.0),
        tube_hole(spars.outer, clr, extend=1.0),
        tube_hole(spars.rear_pin, clr, extend=1.0),
    ]

    parts: list[Part] = []
    for i in range(n_seg):
        ya, yb = float(stations[i]), float(stations[i + 1])
        seg = wing_loft(w, ya, yb, 3)
        for h in holes:
            seg = seg.cut(h)
        if yb > e0 - gap and ya < e1 + gap:
            seg = seg.cut(elevon_void)
        if ya <= ys_servo <= yb:
            seg = seg.cut(servo_pocket)
        if ya < ys_servo:
            seg = seg.cut(wire)
        notes = []
        if i == n_seg - 1:
            # fin locating pins (2 x 3 mm) in the tip face
            for xc in (0.30, 0.65):
                p = w.point_at(yb, xc)
                seg = seg.cut(cylinder(p + [0, -25, 0], p + [0, 2, 0], 3.2))
            notes.append("Tip: 2 x 3 mm CF pins locate the fin")
        seg = _clean(seg)
        name = f"wing_seg{i + 1}_R"
        whole = Part(name, seg, "wing_skin", (0, 1, 0), "wing", "R", notes)
        if printer_fit(whole).fits:
            parts.append(whole)
            continue
        # chordwise split along a constant-x/c line, plane containing z
        xc = fab_wing["chordwise_split_x_over_c"]
        pa, pb = w.point_at(ya, xc), w.point_at(yb, xc)
        d = (pb - pa) / np.linalg.norm(pb - pa)
        nrm = np.array([d[1], -d[0], 0.0])
        if nrm[0] < 0:
            nrm = -nrm
        front = _clean(seg.cut(halfspace(pa, nrm)))
        rear = _clean(seg.intersect(halfspace(pa, nrm)))
        parts.append(Part(name + "_front", front, "wing_skin", (0, 1, 0), "wing", "R",
                          notes + ["Chordwise split: bond front/rear with thin CA + the spar tubes"]))
        parts.append(Part(name + "_rear", rear, "wing_skin", (0, 1, 0), "wing", "R", list(notes)))

    # Elevon pieces
    el_full = wing_loft(w, e0, e1, 4).intersect(halfspace(h0 + n * gap / 2, n))
    # 25 deg bevel on the lower leading edge (top tape hinge) so it can deflect down
    d = (h1 - h0) / np.linalg.norm(h1 - h0)
    beta = math.radians(25.0)
    v = -np.array([0, 0, 1.0]) * math.cos(beta) + n * math.sin(beta)   # down and aft from the hinge
    m = np.cross(d, v)
    probe = -n * 5.0 - np.array([0, 0, 10.0])                           # forward-and-below the hinge
    if np.dot(m, probe) < 0:
        m = -m
    el_full = el_full.cut(halfspace(h0 + n * gap / 2, m))
    k = int(math.ceil((e1 - e0) / fab_wing["elevon_max_piece_mm"]))
    ys = np.linspace(e0, e1, k + 1)
    for i in range(k):
        piece = el_full.intersect(box(-BIG, BIG, float(ys[i]), float(ys[i + 1]), -BIG, BIG))
        parts.append(Part(f"elevon{i + 1}_R", _clean(piece), "elevon", (0, 1, 0), "wing", "R",
                          ["Top-surface tape hinge; sand a 25 deg bevel on the lower leading edge",
                           "Pieces joined on a 3 mm CF rod along the hinge line"] if i == 0 else []))
    return parts


def build_fin(w: WingGeometry, area_mm2: float, height_mm: float, sweep_deg: float = 35.0,
              taper: float = 0.5, airfoil: str = "naca0008") -> Part:
    """Right tip fin (vertical, above the wing tip), NACA 0008."""
    import aerosandbox as asb

    y = w.half_span_mm
    cr = area_mm2 / (0.5 * (1 + taper) * height_mm)
    ct = cr * taper
    x_le = float(w.le_x(y) + w.chord(y)) - cr - 5.0       # fin TE ~ at the wing TE
    tip_top = w.point_at(y, 0.5, "upper")[2]
    u = np.array(asb.Airfoil(airfoil).repanel(n_points_per_side=50).coordinates, float)
    if np.allclose(u[0], u[-1]):
        u = u[:-1]

    def sec(z, c, xle):
        return np.column_stack([xle + u[:, 0] * c, y + u[:, 1] * c, np.full(len(u), z)])

    z0 = tip_top - 3.0
    z1 = z0 + height_mm
    fin = loft([sec(z0, cr, x_le), sec(z1, ct, x_le + height_mm * math.tan(math.radians(sweep_deg)))])
    for xc in (0.30, 0.65):
        p = w.point_at(y, xc)
        fin = fin.cut(cylinder([p[0], y, z0 - 1], [p[0], y, z0 + 22], 3.2))
    return Part("fin_R", _clean(fin), "fin", (0, 1, 0), "wing", "R",
                ["2 x 3 mm CF pins into the wing tip; glue after checking alignment"])


# --------------------------------------------------------------------------- #
# Pod
# --------------------------------------------------------------------------- #

def _pod_lofts(pod: PodGeometry, wall: float, nose_cap: float = 3.0, firewall: float = 4.0):
    xs = [s["x"] for s in pod.sections]
    outer = loft([pod.section(x) for x in xs], kind="smooth")
    xi = list(xs)
    xi[0] = xs[0] + nose_cap + 8.0
    xi[-1] = xs[-1] - firewall
    inner = loft([pod.section(x, inset=wall) for x in xi], kind="smooth")
    return outer, inner


def _fuse_all(solids: list) -> cq.Shape:
    out = solids[0]
    for t in solids[1:]:
        out = out.fuse(t)
    return out


def build_pod(
    w: WingGeometry,
    spars: SparLayout,
    pod: PodGeometry,
    podcfg: dict,
    layout: dict,
    printer_fit,
) -> list[Part]:
    wall = podcfg["wall_mm"]
    outer, inner = _pod_lofts(pod, wall)
    y_side = w.blend_start_mm
    # Wing stub: root airfoil out to the pod side, merged into the pod
    stub = loft([w.section(-y_side), w.section(0.0), w.section(y_side)])
    body = outer.fuse(stub).cut(inner)

    # Rear-pin sockets: a boss on each inner side wall (the pin does NOT cross the
    # pod interior, which keeps the compute bay clear)
    rp = spars.rear_pin
    xr, zr = float(rp.p0[0]), float(rp.p0[2])
    half_in = pod.at(xr)["w"] / 2 - wall
    sockets = [box(xr - 9, xr + 9, (half_in - 18) if sy > 0 else -(half_in + wall + 3),
                   (half_in + wall + 3) if sy > 0 else -(half_in - 18), zr - 9, zr + 9) for sy in (1, -1)]
    body = body.fuse(_fuse_all(sockets).intersect(outer))

    # All small cutters in one boolean
    xcam = layout["cage_lens_axis_x_mm"]
    zb = pod.bottom_z(xcam)
    xn = pod.x_nose
    znose = pod.at(xn)["z"]
    xf = podcfg["firewall_x_mm"]
    zf = pod.at(xf)["z"]
    cutters = [
        cylinder(spars.joiner.p0, spars.joiner.p1, spars.joiner.od_mm + 0.4, extend=5),
        cylinder([xr, half_in - 16, zr], [xr, 200, zr], rp.od_mm + 0.3),
        cylinder([xr, -200, zr], [xr, -(half_in - 16), zr], rp.od_mm + 0.3),
        cylinder([xcam, 0, zb - 10], [xcam, 0, zb + 15], podcfg["camera_window_d_mm"]),
        cylinder([xn - 5, 0, znose], [xn + 20, 0, znose], 4.5),                              # pitot
        box(-75, -25, -22, 22, pod.bottom_z(-50) - 5, pod.bottom_z(-50) + 6),                # cooling inlet
        box(310, 345, -20, 20, pod.bottom_z(330) - 5, pod.bottom_z(330) + 6),                # cooling outlet
        cylinder([xf - 10, 0, zf], [xf + 5, 0, zf], podcfg["motor_shaft_hole_mm"]),
    ]
    r0, r1 = podcfg["motor_slot_r_mm"]
    for ang in (45, 135, 225, 315):
        a = math.radians(ang)
        c0 = [xf - 10, r0 * math.cos(a), zf + r0 * math.sin(a)]
        c1 = [xf - 10, r1 * math.cos(a), zf + r1 * math.sin(a)]
        # slot = two end cylinders + a box-like hull (approximated by 4 cylinders)
        for t_ in np.linspace(0, 1, 4):
            c = np.array(c0) + t_ * (np.array(c1) - np.array(c0))
            cutters.append(cylinder(c, [xf + 5, c[1], c[2]], 3.3))
    # NB: fuse the tools first — OCC mis-handles a compound of *overlapping* tools
    body = _clean(body.cut(_fuse_all(cutters)))

    # Hatches: the top is cut off over each bay, leaving bridges between them
    zc = podcfg["hatch_z_above_mm"]
    hatch_boxes = [box(a, b, -BIG, BIG, zc, BIG) for a, b in podcfg["hatches_x_mm"]]
    hatches = [body.intersect(hb) for hb in hatch_boxes]
    body = body.cut(_fuse_all(hatch_boxes))
    names_h = podcfg.get("hatch_names", [f"hatch{i + 1}" for i in range(len(hatches))])
    parts: list[Part] = []
    for i, h in enumerate(hatches):
        for a, b in [podcfg["hatches_x_mm"][i]]:
            if a <= xcam <= b:
                h = h.cut(cylinder([xcam, 0, 0], [xcam, 0, 200], 42))   # antenna mast passage
        parts.append(Part(f"hatch_{names_h[i]}", _clean(h), "hatch", (0, 0, 1), "pod", "C",
                          ["Retain with 6x2 mm magnets + a front tongue; tape the seam for flight"]))

    # Transverse print splits
    splits = sorted(podcfg["split_x_mm"])
    edges = [pod.x_nose - 10] + splits + [pod.x_tail + 10]
    names = ["pod_nose", "pod_mid", "pod_tail"]
    for i in range(len(edges) - 1):
        piece = body.intersect(box(edges[i], edges[i + 1], -BIG, BIG, -BIG, BIG))
        parts.append(Part(names[i] if i < len(names) else f"pod_{i}", _clean(piece), "pod_shell",
                          (-1, 0, 0) if i < len(edges) - 2 else (1, 0, 0), "pod", "C",
                          ["Print standing on the split face"]))

    # Joint rings at each split (separate parts, glued inside both pieces)
    lip = podcfg["lip_mm"]
    for k, xs in enumerate(splits):
        ring = loft([pod.section(xs - lip, inset=wall), pod.section(xs + lip, inset=wall)], kind="smooth")
        ring = ring.cut(loft([pod.section(xs - lip, inset=wall + 1.6), pod.section(xs + lip, inset=wall + 1.6)],
                             kind="smooth"))
        ring = ring.cut(box(-BIG, BIG, -BIG, BIG, zc - 1, BIG))       # open where the hatch is
        parts.append(Part(f"pod_joint_ring{k + 1}", _clean(ring), "pod_shell", (1, 0, 0), "pod", "C",
                          ["Glue half into each neighbouring pod piece"]))

    # Spar box (ASA-CF): a ring frame bonded to the shell, plus two lugs that
    # carry the joiner at the side walls. The joiner itself is the carry-through.
    t = spars.joiner
    xb, zj = float(t.p0[0]), float(t.p0[2])
    frame_w = podcfg.get("frame_width_mm", 10.0)
    outer_r = loft([pod.section(xb - 3, inset=wall + 0.2), pod.section(xb + 3, inset=wall + 0.2)], kind="smooth")
    inner_r = loft([pod.section(xb - 3, inset=wall + frame_w), pod.section(xb + 3, inset=wall + frame_w)], kind="smooth")
    frame = outer_r.cut(inner_r)
    hw = pod.at(xb)["w"] / 2 - wall
    lugs = _fuse_all([
        box(xb - 12, xb + 12, hw - 22, hw + 0.5, zj - t.od_mm / 2 - 6, zj + t.od_mm / 2 + 6),
        box(xb - 12, xb + 12, -hw - 0.5, -(hw - 22), zj - t.od_mm / 2 - 6, zj + t.od_mm / 2 + 6),
    ]).intersect(outer_r.fuse(loft([pod.section(xb - 12, inset=wall + 0.2), pod.section(xb + 12, inset=wall + 0.2)],
                                     kind="smooth")))
    sbox = frame.fuse(lugs)
    sbox = sbox.cut(box(-BIG, BIG, -BIG, BIG, zc - 2, BIG))
    sbox = sbox.cut(cylinder([xb, -200, zj], [xb, 200, zj], t.od_mm + 0.3))
    parts.append(Part("spar_box", _clean(sbox), "structural", (1, 0, 0), "pod", "C",
                      ["Ring frame + joiner lugs; bond into the pod mid section",
                       "The 14 mm joiner is the carry-through — slide it through both lugs"]))
    return parts


def build_skid(pod: PodGeometry, podcfg: dict, layout: dict) -> list[Part]:
    """Sacrificial belly skids, split at the camera window."""
    w = podcfg["skid_width_mm"]
    x0, x1 = -110.0, 300.0
    xs = np.linspace(x0, x1, 12)
    outer, _ = _pod_lofts(pod, podcfg["wall_mm"])
    zmin = min(pod.bottom_z(x) for x in xs)
    slab = box(x0, x1, -w / 2, w / 2, zmin - 4.0, zmin + 25)
    shifted = outer.translate(cq.Vector(0, 0, -3.5))      # 3.5 mm layer that follows the belly
    skid = slab.intersect(shifted).cut(outer)
    xcam = layout["cage_lens_axis_x_mm"]
    rw = podcfg["camera_window_d_mm"] / 2 + 4
    out = []
    for name, (a, b) in (("belly_skid_front", (x0, xcam - rw)), ("belly_skid_rear", (xcam + rw, x1))):
        piece = skid.intersect(box(a, b, -BIG, BIG, -BIG, BIG))
        out.append(Part(name, _clean(piece), "skid", (0, 0, -1), "pod", "C",
                        ["Sacrificial; servo tape or M3 into heat-set inserts"]))
    return out


# --------------------------------------------------------------------------- #
# Survey cage
# --------------------------------------------------------------------------- #

def build_cage(pod: PodGeometry, payload_members: dict, layout: dict, standoff: float, wall: float) -> Part:
    """Rigid camera + GNSS cage (ASA-CF), lens axis at layout x, centred on y=0."""
    xc = layout["cage_lens_axis_x_mm"]
    z0 = pod.bottom_z(xc) + wall + standoff                 # lens front face
    lens = payload_members["lens"]["envelope_mm"]
    cam = payload_members["camera"]["envelope_mm"]
    rx = payload_members["gnss_receiver"]
    ant = payload_members["gnss_antenna"]
    lens_d = lens[0]
    ring_z0, ring_h = z0 + 20.0, 16.0
    # lens clamp ring
    ring = cq.Solid.makeCylinder(lens_d / 2 + 5, ring_h, cq.Vector(xc, 0, ring_z0))
    ring = ring.cut(cq.Solid.makeCylinder(lens_d / 2 + 0.3, ring_h, cq.Vector(xc, 0, ring_z0)))
    ring = ring.cut(box(xc + lens_d / 2 - 2, xc + lens_d / 2 + 8, -1.0, 1.0, ring_z0, ring_z0 + ring_h))  # clamp slot
    boss = box(xc + lens_d / 2 + 2, xc + lens_d / 2 + 12, -7, 7, ring_z0, ring_z0 + ring_h)
    boss = boss.cut(box(xc + lens_d / 2 + 2, xc + lens_d / 2 + 12, -1.0, 1.0, ring_z0, ring_z0 + ring_h))
    boss = boss.cut(cylinder([xc + lens_d / 2 + 7.5, -8, ring_z0 + ring_h / 2], [xc + lens_d / 2 + 7.5, 8, ring_z0 + ring_h / 2], 3.3))
    # base plate with damper tabs
    half = 46.0
    base = box(xc - half, xc + half, -half, half, ring_z0, ring_z0 + 4)
    base = base.cut(cq.Solid.makeCylinder(lens_d / 2 + 0.3, 10, cq.Vector(xc, 0, ring_z0 - 1)))
    for sx in (-1, 1):
        for sy in (-1, 1):
            base = base.cut(cq.Solid.makeCylinder(4.2, 10, cq.Vector(xc + sx * (half - 8), sy * (half - 8), ring_z0 - 1)))
    # posts up to the receiver plate
    top_z = z0 + rx["position_mm"][2] - 4
    posts = None
    for sx in (-1, 1):
        for sy in (-1, 1):
            p = box(xc + sx * (half - 18) - 5, xc + sx * (half - 18) + 5, sy * (half - 18) - 5,
                    sy * (half - 18) + 5, ring_z0 + 4, top_z)
            posts = p if posts is None else posts.fuse(p)
    # camera saddle at camera mid-height
    cz = z0 + payload_members["camera"]["position_mm"][2] + cam[2] / 2
    post_c = half - 18
    saddle = box(xc - post_c - 5, xc + post_c + 5, -post_c, -cam[1] / 2 - 1, cz - 8, cz + 8)
    saddle = saddle.fuse(box(xc - post_c - 5, xc + post_c + 5, cam[1] / 2 + 1, post_c, cz - 8, cz + 8))
    for sy in (-1, 1):
        saddle = saddle.cut(cylinder([xc, sy * (cam[1] / 2 - 2), cz], [xc, sy * (cam[1] / 2 + 8), cz], 2.4))
    # receiver plate + antenna mast
    plate = box(xc - 40, xc + 40, -34, 34, top_z, top_z + 4)
    for sx in (-1, 1):
        for sy in (-1, 1):
            plate = plate.cut(cq.Solid.makeCylinder(1.4, 10, cq.Vector(xc + sx * 30.5, sy * 23, top_z - 1)))
    mast_top = z0 + ant["position_mm"][2]
    mast = cq.Solid.makeCylinder(8, mast_top - top_z, cq.Vector(xc, 0, top_z))
    mast = mast.cut(cq.Solid.makeCylinder(5, mast_top - top_z + 2, cq.Vector(xc, 0, top_z - 1)))
    disc = cq.Solid.makeCylinder(16, 4, cq.Vector(xc, 0, mast_top - 4))
    disc = disc.cut(cq.Solid.makeCylinder(3.2, 6, cq.Vector(xc, 0, mast_top - 5)))
    cage = ring.fuse(boss).fuse(base).fuse(posts).fuse(saddle).fuse(plate).fuse(mast).fuse(disc)
    return Part("survey_cage", _clean(cage), "structural", (0, 0, 1), "payload", "C",
                ["Camera + lens + F9P + helical antenna as ONE rigid unit",
                 "4 x M3 rubber dampers under the base tabs — the only compliance in the chain",
                 "Lens clamp: M3 through the boss; camera saddle: M2 into the housing"])


def build_tray(pod: PodGeometry, layout: dict, wall: float, x_start: float) -> Part:
    """Universal avionics/compute tray: 3 mm plate with a 10 mm M3 grid, aft of the spar box."""
    x0, x1 = x_start, layout["esc_x_mm"] + 5
    xm = 0.5 * (x0 + x1)
    zt = pod.bottom_z(xm) + 30
    width = pod.at(x1)["w"] - 2 * wall - 12
    plate = box(x0, x1, -width / 2, width / 2, zt, zt + 3)
    for gx in np.arange(x0 + 10, x1 - 5, 10.0):
        for gy in np.arange(-width / 2 + 10, width / 2 - 5, 10.0):
            plate = plate.cut(cq.Solid.makeCylinder(1.7, 5, cq.Vector(float(gx), float(gy), zt - 1)))
    return Part("avionics_tray", _clean(plate), "structural", (0, 0, 1), "pod", "C",
                ["Orin/CM5 carrier, ESC, regulators and FC on standoffs; rests on the bulkhead and pod floor"])
