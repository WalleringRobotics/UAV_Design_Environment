"""Printer profile and the "does this part fit" check.

A part fits if, printed with its chosen axis vertical, its footprint fits
inside the bed (minus margin) at *some* rotation about that axis, and its
height fits under the gantry. The rotation search is a brute-force sweep of
the convex hull's bounding box — exact enough at 0.5 degree steps and robust
for any shape.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PrinterProfile:
    name: str
    bed_x_mm: float
    bed_y_mm: float
    max_z_mm: float
    margin_mm: float = 5.0

    @classmethod
    def from_dict(cls, d: dict) -> "PrinterProfile":
        return cls(d["name"], float(d["bed_x_mm"]), float(d["bed_y_mm"]), float(d["max_z_mm"]),
                   float(d.get("margin_mm", 5.0)))

    @property
    def usable_xy(self) -> tuple[float, float]:
        return self.bed_x_mm - 2 * self.margin_mm, self.bed_y_mm - 2 * self.margin_mm


@dataclass(frozen=True)
class Fit:
    fits: bool
    angle_deg: float          # rotation about the print axis that fits (or the best found)
    footprint_mm: tuple[float, float]
    height_mm: float
    slack_mm: float           # smallest remaining clearance in X/Y at the chosen angle (negative = overflow)

    def as_dict(self) -> dict:
        return {"fits": self.fits, "angle_deg": self.angle_deg,
                "footprint_mm": [round(v, 1) for v in self.footprint_mm],
                "height_mm": round(self.height_mm, 1), "slack_mm": round(self.slack_mm, 1)}


def _hull_2d(pts: np.ndarray) -> np.ndarray:
    """Monotone-chain convex hull."""
    pts = np.unique(np.round(pts, 4), axis=0)
    if len(pts) < 3:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def orient_to_axis(vertices: np.ndarray, up: np.ndarray) -> np.ndarray:
    """Rotate vertices so that `up` becomes +Z (Rodrigues)."""
    up = np.asarray(up, float)
    up = up / np.linalg.norm(up)
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(up, z)
    c = float(np.dot(up, z))
    if np.linalg.norm(v) < 1e-12:
        return vertices.copy() if c > 0 else vertices * np.array([1, -1, -1])
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    r = np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))
    return vertices @ r.T


def check_fit(vertices: np.ndarray, printer: PrinterProfile, up=(0, 0, 1), step_deg: float = 0.5) -> Fit:
    """Can the part be printed with `up` vertical on this printer?"""
    v = orient_to_axis(np.asarray(vertices, float), np.asarray(up, float))
    height = float(v[:, 2].max() - v[:, 2].min())
    hull = _hull_2d(v[:, :2])
    ux, uy = printer.usable_xy
    best = (-np.inf, 0.0, (0.0, 0.0))
    for a in np.arange(0.0, 180.0, step_deg):
        t = np.radians(a)
        rot = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
        p = hull @ rot.T
        w, h = np.ptp(p[:, 0]), np.ptp(p[:, 1])
        slack = min(ux - w, uy - h)
        if slack > best[0]:
            best = (slack, float(a), (float(w), float(h)))
    slack, ang, fp = best
    fits = slack >= 0 and height <= printer.max_z_mm - printer.margin_mm
    return Fit(fits, ang, fp, height, float(slack))
