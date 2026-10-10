"""Airframe geometry for fabrication (pure numpy — no CAD kernel needed).

Aircraft frame, millimetres:
    x  aft, from the wing root leading edge
    y  right, from the centreline (the right half is modelled; left is a mirror)
    z  up, from the root chord plane

Wing sections use the same airfoil blend, twist and planform as the
stability analysis (:mod:`uavdesign.aero.stability`), so what is printed is
what was analysed. Twist (washout) rotates each section nose-down about its
leading edge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np


@lru_cache(maxsize=256)
def _blended_coords(root: str, tip: str, blend: float, n: int, te_thickness: float) -> np.ndarray:
    """Unit-chord section, upper surface TE->LE then lower LE->TE, no repeated point.

    The trailing edge is opened to `te_thickness` (fraction of chord) by
    adding +/- t/2 * x/c to the upper/lower surfaces, so thin printed edges
    have something to print and the polygon never self-intersects.
    """
    import aerosandbox as asb

    af = asb.Airfoil(root).repanel(n_points_per_side=n)
    if tip != root and blend > 1e-6:
        af = af.blend_with_another_airfoil(asb.Airfoil(tip).repanel(n_points_per_side=n),
                                           blend_fraction=blend, n_points_per_side=n)
    c = np.array(af.coordinates, float)
    if np.allclose(c[0], c[-1]):
        c = c[:-1]
    i_le = int(np.argmin(c[:, 0]))
    first, second = c[: i_le + 1], c[i_le:]
    if np.mean(first[:, 1]) < np.mean(second[:, 1]):      # make sure we start on the upper surface
        c = c[::-1]
        i_le = len(c) - 1 - i_le
    up, lo = c[: i_le + 1].copy(), c[i_le + 1:].copy()
    up[:, 1] += 0.5 * te_thickness * up[:, 0]
    lo[:, 1] -= 0.5 * te_thickness * lo[:, 0]
    out = np.vstack([up, lo])
    # drop near-duplicate neighbours (closing TE points, LE cluster)
    keep = [0]
    for i in range(1, len(out)):
        if np.linalg.norm(out[i] - out[keep[-1]]) > 1e-5:
            keep.append(i)
    out = out[keep]
    if np.linalg.norm(out[0] - out[-1]) < 1e-5:
        out = out[:-1]
    return out


@dataclass
class WingGeometry:
    root_chord_mm: float
    tip_chord_mm: float
    half_span_mm: float
    le_sweep_deg: float
    washout_deg: float
    airfoil_root: str
    airfoil_tip: str
    blend_start_mm: float = 0.0
    te_thickness_mm: float = 0.9
    n_points_per_side: int = 90

    @classmethod
    def from_airframe(cls, g: dict, te_thickness_mm: float = 0.9, n: int = 90) -> "WingGeometry":
        return cls(g["root_chord_mm"], g["tip_chord_mm"], g["half_span_mm"], g["le_sweep_deg"],
                   g["washout_deg"], g["airfoil_root"], g["airfoil_tip"], g["pod_width_mm"] / 2,
                   te_thickness_mm, n)

    # ---- planform ----------------------------------------------------------

    def le_x(self, y):
        return np.abs(np.asarray(y, float)) * math.tan(math.radians(self.le_sweep_deg))

    def chord(self, y):
        eta = np.clip(np.abs(np.asarray(y, float)) / self.half_span_mm, 0, 1)
        return self.root_chord_mm + (self.tip_chord_mm - self.root_chord_mm) * eta

    def twist_deg(self, y):
        """Nose-down rotation (deg) of the section at y."""
        return self.washout_deg * np.abs(np.asarray(y, float)) / self.half_span_mm

    def blend(self, y: float) -> float:
        y = abs(y)
        if y <= self.blend_start_mm:
            return 0.0
        return min(1.0, (y - self.blend_start_mm) / (self.half_span_mm - self.blend_start_mm))

    # ---- sections ------------------------------------------------------------

    def unit_section(self, y: float) -> np.ndarray:
        c = self.chord(y)
        te = self.te_thickness_mm / float(c)
        return _blended_coords(self.airfoil_root, self.airfoil_tip, round(self.blend(y), 4),
                               self.n_points_per_side, round(te, 5))

    def section(self, y: float) -> np.ndarray:
        """Closed section polygon at span station y, shape (N, 3)."""
        u = self.unit_section(y)
        c = float(self.chord(y))
        t = math.radians(float(self.twist_deg(y)))
        dx, dz = u[:, 0] * c, u[:, 1] * c
        x = float(self.le_x(y)) + dx * math.cos(t) - dz * math.sin(t)
        z = dz * math.cos(t) + dx * math.sin(t)
        return np.column_stack([x, np.full_like(x, float(y)), z])

    def point_at(self, y: float, x_over_c: float, where: str = "camber") -> np.ndarray:
        """3-D point on the camber line ('camber'), upper or lower surface at x/c."""
        import aerosandbox as asb  # noqa: F401  (ensures the cache path is available)

        u = self.unit_section(y)
        i_le = int(np.argmin(u[:, 0]))
        up, lo = u[: i_le + 1][::-1], u[i_le:]
        zu = np.interp(x_over_c, up[:, 0], up[:, 1])
        zl = np.interp(x_over_c, lo[:, 0], lo[:, 1])
        zc = {"camber": 0.5 * (zu + zl), "upper": zu, "lower": zl}[where]
        c = float(self.chord(y))
        t = math.radians(float(self.twist_deg(y)))
        dx, dz = x_over_c * c, zc * c
        return np.array([float(self.le_x(y)) + dx * math.cos(t) - dz * math.sin(t), float(y),
                         dz * math.cos(t) + dx * math.sin(t)])

    def thickness_at(self, y: float, x_over_c: float) -> float:
        """Local section thickness (mm) at x/c."""
        u = self.unit_section(y)
        i_le = int(np.argmin(u[:, 0]))
        up, lo = u[: i_le + 1][::-1], u[i_le:]
        return float((np.interp(x_over_c, up[:, 0], up[:, 1]) - np.interp(x_over_c, lo[:, 0], lo[:, 1]))
                     * self.chord(y))

    def x_over_c_of(self, y: float, x: float) -> float:
        return (x - float(self.le_x(y))) / float(self.chord(y))


@dataclass
class TubePath:
    """A straight tube: centreline from p0 to p1 (mm), with outer diameter."""

    name: str
    p0: np.ndarray
    p1: np.ndarray
    od_mm: float
    id_mm: float

    @property
    def length_mm(self) -> float:
        return float(np.linalg.norm(self.p1 - self.p0))

    @property
    def direction(self) -> np.ndarray:
        d = self.p1 - self.p0
        return d / np.linalg.norm(d)


@dataclass
class SparLayout:
    joiner: TubePath
    sleeve: TubePath
    outer: TubePath
    rear_pin: TubePath
    checks: dict = field(default_factory=dict)


def spar_layout(wing: WingGeometry, spars: dict, pod_half_width_mm: float, rear_pin_x_over_c_root: float = 0.72) -> SparLayout:
    """Place the joiner, sleeve, swept outer spar and rear pin inside the wing.

    The straight joiner's x is chosen midway between the most-aft and
    most-forward positions that keep it inside 15-60 % chord over its whole
    length, and on the mean camber line at mid-length (z).
    """
    j, sl, o, rp = spars["joiner"], spars["sleeve"], spars["outer_spar"], spars["rear_pin"]
    y_tip_j = j["half_length_mm"]
    ys = np.linspace(0, y_tip_j + 15, 40)
    x_min = max(float(wing.le_x(y) + 0.15 * wing.chord(y)) for y in ys)
    x_max = min(float(wing.le_x(y) + 0.60 * wing.chord(y)) for y in ys)
    if x_min > x_max:
        raise ValueError("joiner cannot stay inside 15-60 % chord over its length; shorten it")
    xj = 0.5 * (x_min + x_max)
    zj = float(np.mean([wing.point_at(y, wing.x_over_c_of(y, xj))[2] for y in (0.0, y_tip_j)]))
    joiner = TubePath("joiner", np.array([xj, -y_tip_j, zj]), np.array([xj, y_tip_j, zj]), j["od_mm"], j["id_mm"])
    sleeve = TubePath("sleeve", np.array([xj, pod_half_width_mm, zj]), np.array([xj, y_tip_j + 15, zj]),
                      sl["od_mm"], sl["id_mm"])

    h = wing.half_span_mm
    y0, y1 = o["y_start_fraction"] * h, o["y_end_fraction"] * h
    outer = TubePath("outer_spar", wing.point_at(y0, o["x_over_c"]), wing.point_at(y1, o["x_over_c"]),
                     o["od_mm"], o["id_mm"])

    xr = rear_pin_x_over_c_root * wing.root_chord_mm
    yr = rp["half_length_mm"]
    zr = float(np.mean([wing.point_at(y, wing.x_over_c_of(y, xr))[2] for y in (0.0, yr)]))
    rear = TubePath("rear_pin", np.array([xr, -yr, zr]), np.array([xr, yr, zr]), rp["od_mm"], rp["id_mm"])

    # Wall checks: tube must sit inside the local thickness with >= 1.5 mm skin each side
    checks = {}
    for t in (sleeve, outer, rear):
        worst = np.inf
        for s in np.linspace(0, 1, 15):
            p = t.p0 + s * (t.p1 - t.p0)
            if p[1] < pod_half_width_mm:
                continue
            xc = wing.x_over_c_of(p[1], p[0])
            worst = min(worst, wing.thickness_at(p[1], xc) - t.od_mm)
        checks[t.name] = {"min_thickness_margin_mm": float(worst), "ok": bool(worst >= 3.0)}
    return SparLayout(joiner, sleeve, outer, rear, checks)


# --------------------------------------------------------------------------- #
# Pod
# --------------------------------------------------------------------------- #

def superellipse(width: float, height: float, n: float, z_c: float, count: int = 72) -> np.ndarray:
    """(y, z) points of a superellipse cross-section, counter-clockwise from +y."""
    t = np.linspace(0, 2 * np.pi, count, endpoint=False)
    c, s = np.cos(t), np.sin(t)
    y = width / 2 * np.sign(c) * np.abs(c) ** (2.0 / n)
    z = z_c + height / 2 * np.sign(s) * np.abs(s) ** (2.0 / n)
    return np.column_stack([y, z])


@dataclass
class PodGeometry:
    sections: list           # dicts: x, w, h, z, n

    @classmethod
    def from_dict(cls, d: dict) -> "PodGeometry":
        return cls(sorted(d["sections"], key=lambda s: s["x"]))

    def _interp(self, x: float, key: str) -> float:
        xs = [s["x"] for s in self.sections]
        return float(np.interp(x, xs, [s[key] for s in self.sections]))

    def at(self, x: float) -> dict:
        return {k: self._interp(x, k) for k in ("w", "h", "z", "n")}

    def bottom_z(self, x: float) -> float:
        s = self.at(x)
        return s["z"] - s["h"] / 2

    def top_z(self, x: float) -> float:
        s = self.at(x)
        return s["z"] + s["h"] / 2

    def section(self, x: float, inset: float = 0.0, count: int = 72) -> np.ndarray:
        s = self.at(x)
        yz = superellipse(max(s["w"] - 2 * inset, 1.0), max(s["h"] - 2 * inset, 1.0), s["n"], s["z"], count)
        return np.column_stack([np.full(len(yz), x), yz[:, 0], yz[:, 1]])

    @property
    def x_nose(self) -> float:
        return self.sections[0]["x"]

    @property
    def x_tail(self) -> float:
        return self.sections[-1]["x"]
