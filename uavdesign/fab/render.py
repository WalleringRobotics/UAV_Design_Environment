"""Matplotlib previews of the assembled airframe (no OpenGL needed)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

GROUP_COLOURS = {
    "wing": "#c9d3dc",
    "pod": "#7f8c99",
    "payload": "#d9822b",
}
PROFILE_COLOURS = {"structural": "#2b2f33", "skid": "#4f7a5a", "elevon": "#9fb3c4", "fin": "#aebdca"}


def _mesh(shape, tol: float):
    v, t = shape.tessellate(tol, 0.5)
    return np.array([[p.x, p.y, p.z] for p in v]), np.array(t)


def _shade(normals: np.ndarray, base: str) -> np.ndarray:
    light = np.array([-0.4, -0.5, 0.75])
    light /= np.linalg.norm(light)
    k = 0.45 + 0.55 * np.clip(np.abs(normals @ light), 0, 1)
    rgb = np.array(matplotlib.colors.to_rgb(base))
    return np.clip(rgb[None, :] * k[:, None], 0, 1)


def render(parts, path: str | Path, view=(28, -125), tol: float = 1.5, title: str | None = None,
           exploded: float = 0.0, figsize=(12, 7), cutaway_groups: tuple = (), zoom: float = 1.25) -> Path:
    """Shaded render of BuiltPart/Part objects.

    `exploded` pushes wing pieces apart (mm); parts in `cutaway_groups` are
    cut at y = 0 (the +y half removed) to show what is inside.
    """
    import cadquery as cq

    fig = plt.figure(figsize=figsize)
    ax = fig.add_subplot(111, projection="3d")
    ax.set_proj_type("ortho")
    allv = []
    keep = cq.Solid.makeBox(4000, 2000, 4000, cq.Vector(-2000, -2000, -2000))
    for bp in parts:
        part = getattr(bp, "part", bp)
        solid = part.solid.intersect(keep) if part.group in cutaway_groups else part.solid
        v, t = _mesh(solid, tol)
        if len(t) == 0:
            continue
        if exploded and part.group == "wing":
            v = v + np.array([0, np.sign(v[:, 1].mean()) * exploded, 0])
        tri = v[t]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        base = PROFILE_COLOURS.get(part.profile, GROUP_COLOURS.get(part.group, "#bbbbbb"))
        pc = Poly3DCollection(tri, facecolors=_shade(n, base), edgecolors="none", linewidths=0)
        ax.add_collection3d(pc)
        allv.append(v)
    v = np.vstack(allv)
    lo, hi = v.min(0), v.max(0)
    ax.set_xlim(lo[0], hi[0])
    ax.set_ylim(lo[1], hi[1])
    ax.set_zlim(lo[2], hi[2])
    ax.set_box_aspect(tuple(np.maximum(hi - lo, 1.0)), zoom=zoom)
    ax.view_init(*view)
    ax.set_axis_off()
    fig.subplots_adjust(0, 0, 1, 0.94 if title else 1)
    if title:
        fig.suptitle(title)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path
