"""Headless, depth-buffered orthographic previews of the assembled airframe.

Projection and rasterization use NumPy. This avoids Matplotlib's per-collection
painter ordering, which can draw hidden triangles over an enclosing pod shell.
Pillow, already required by Matplotlib, writes the antialiased PNG and title.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.colors
import numpy as np
from PIL import Image, ImageDraw, ImageFont

GROUP_COLOURS = {"wing": "#c9d3dc", "pod": "#7f8c99", "payload": "#d9822b"}
PROFILE_COLOURS = {"structural": "#39444b", "skid": "#4f7a5a", "elevon": "#9fb3c4", "fin": "#aebdca"}


def _mesh(shape, tol: float):
    vertices, triangles = shape.tessellate(tol, 0.35)
    return np.array([[p.x, p.y, p.z] for p in vertices]), np.asarray(triangles, dtype=np.int32)


def _camera(view):
    elevation, azimuth = np.radians(view)
    eye = np.array([np.cos(elevation) * np.cos(azimuth),
                    np.cos(elevation) * np.sin(azimuth), np.sin(elevation)])
    right = np.array([-np.sin(azimuth), np.cos(azimuth), 0.0])
    up = np.cross(eye, right)
    return np.column_stack([right, up, eye])


def _vertex_light(vertices, triangles):
    """Smooth within a CAD face; tessellation keeps sharp face seams separate."""
    xyz = vertices[triangles]
    normals = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
    smooth = np.zeros_like(vertices)
    for corner in range(3):
        np.add.at(smooth, triangles[:, corner], normals)
    smooth /= np.linalg.norm(smooth, axis=1, keepdims=True) + 1e-12
    light = np.array([-0.4, -0.5, 0.75])
    light /= np.linalg.norm(light)
    return 0.55 + 0.45 * np.abs(smooth @ light)


def _rasterize(projected, triangles, brightness, colour, pixels, depth):
    """Rasterize with interpolated depth: larger camera Z is nearer the eye."""
    height, width = depth.shape
    rgb = np.asarray(matplotlib.colors.to_rgb(colour)) * 255
    for indices in triangles:
        p = projected[indices]
        xmin, ymin = np.maximum(np.floor(p[:, :2].min(0)).astype(int), 0)
        xmax, ymax = np.minimum(np.ceil(p[:, :2].max(0)).astype(int), [width - 1, height - 1])
        if xmin > xmax or ymin > ymax:
            continue
        a, b, c = p[:, :2]
        denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(denominator) < 1e-9:
            continue
        x = np.arange(xmin, xmax + 1)[None, :] + 0.5
        y = np.arange(ymin, ymax + 1)[:, None] + 0.5
        wa = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / denominator
        wb = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / denominator
        wc = 1.0 - wa - wb
        z = wa * p[0, 2] + wb * p[1, 2] + wc * p[2, 2]
        window = depth[ymin:ymax + 1, xmin:xmax + 1]
        visible = (wa >= -1e-7) & (wb >= -1e-7) & (wc >= -1e-7) & (z > window)
        if not np.any(visible):
            continue
        window[visible] = z[visible]
        levels = brightness[indices]
        shade = wa[visible] * levels[0] + wb[visible] * levels[1] + wc[visible] * levels[2]
        pixels[ymin:ymax + 1, xmin:xmax + 1][visible] = np.clip(shade[:, None] * rgb, 0, 255).astype(np.uint8)


def render(parts, path: str | Path, view=(28, -125), tol: float = 1.5, title: str | None = None,
           exploded: float = 0.0, figsize=(12, 7), cutaway_groups: tuple = (), zoom: float = 1.25) -> Path:
    """Render BuiltPart/Part objects with a fitted, unclipped orthographic camera.

    ``exploded`` separates the two wing panels in y. ``cutaway_groups`` removes
    the +y half; view from a positive azimuth to see into the opening. ``zoom``
    controls framing padding and never crops geometry. Coordinates retain equal
    scale in both screen directions, including top views of wide wings.
    """
    import cadquery as cq

    if zoom <= 0 or not np.isfinite(zoom) or min(figsize) <= 0:
        raise ValueError("zoom and image dimensions must be positive and finite")
    camera = _camera(view)
    meshes = []
    keep = cq.Solid.makeBox(4000, 2000, 4000, cq.Vector(-2000, -2000, -2000))
    for bp in parts:
        part = getattr(bp, "part", bp)
        solid = part.solid.intersect(keep) if part.group in cutaway_groups else part.solid
        vertices, triangles = _mesh(solid, tol)
        if not len(triangles):
            continue
        if exploded and part.group == "wing":
            vertices = vertices + [0, np.sign(vertices[:, 1].mean()) * exploded, 0]
        base = (GROUP_COLOURS["payload"] if part.group == "payload" else
                PROFILE_COLOURS.get(part.profile, GROUP_COLOURS.get(part.group, "#bbbbbb")))
        meshes.append((vertices @ camera, triangles, _vertex_light(vertices, triangles), base))
    if not meshes:
        raise ValueError("No drawable triangles in preview")

    projected = np.vstack([mesh[0] for mesh in meshes])
    lower, upper = projected[:, :2].min(0), projected[:, :2].max(0)
    extent = np.maximum(upper - lower, 1.0)
    center = (lower + upper) / 2
    width, height = (int(round(float(size) * 140)) for size in figsize)
    margin = max(16, round(min(width, height) * 0.055 / zoom))
    title_height = 52 if title else 0
    scale = min((width - 2 * margin) / extent[0],
                (height - 2 * margin - title_height) / extent[1])
    # Two samples per output pixel preserve thin trailing edges and small holes.
    samples = 2
    pixels = np.full((height * samples, width * samples, 3), 255, dtype=np.uint8)
    depth = np.full((height * samples, width * samples), -np.inf, dtype=np.float32)
    for points, triangles, brightness, colour in meshes:
        screen = points.copy()
        screen[:, 0] = (points[:, 0] - center[0]) * scale + width / 2
        screen[:, 1] = -(points[:, 1] - center[1]) * scale + (height + title_height) / 2
        screen[:, :2] *= samples
        _rasterize(screen, triangles, brightness, colour, pixels, depth)
    preview = Image.fromarray(pixels).resize((width, height), Image.Resampling.LANCZOS)
    if title:
        from matplotlib.font_manager import findfont

        font = ImageFont.truetype(findfont("DejaVu Sans"), 25)
        ImageDraw.Draw(preview).text((width / 2, 16), title, fill="#17212b", font=font, anchor="mt")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(path)
    return path
