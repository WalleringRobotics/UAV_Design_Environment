"""Offline, hash-bound plate planning from an existing CAD artifact inventory.

The result is arranged geometry, not machine instructions. Mesh orientation is
preserved; only translations and rotations about the vertical Z axis are used.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
import shutil
import struct
import tempfile
from pathlib import Path, PurePosixPath

import numpy as np

from .three_mf import write_plate


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _number(value, name, *, positive=False):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'} and finite")
    return value


def _safe_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("Invalid artifact path")
    path = PurePosixPath(relative)
    resolved = (root / relative).resolve()
    if path.is_absolute() or ".." in path.parts or not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"Artifact path escapes inventory or is missing: {relative}")
    return resolved


def _triangles(data: bytes, name: str) -> np.ndarray:
    if len(data) < 84:
        raise ValueError(f"Invalid binary STL header: {name}")
    count = struct.unpack_from("<I", data, 80)[0]
    if not count or len(data) != 84 + count * 50:
        raise ValueError(f"Invalid binary STL triangle count or length: {name}")
    dtype = np.dtype([("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")])
    records = np.frombuffer(data, dtype=dtype, count=count, offset=84)
    if not np.all(np.isfinite(records["vertices"])) or not np.all(np.isfinite(records["normal"])):
        raise ValueError(f"Nonfinite STL coordinates or normals: {name}")
    result = records["vertices"].astype(np.float64)
    if np.any(np.ptp(result.reshape(-1, 3), axis=0) <= 0):
        raise ValueError(f"STL must have positive three-dimensional extent: {name}")
    return result


def _convex(points):
    """Exact-coordinate convex hull; no preview rounding enters placement checks."""
    from scipy.spatial import ConvexHull
    points = np.asarray(points, dtype=float)
    return points[ConvexHull(points).vertices]


def _area(polygon):
    return abs(float(np.sum(polygon[:, 0] * np.roll(polygon[:, 1], -1)
                            - polygon[:, 1] * np.roll(polygon[:, 0], -1)))) / 2


def _minkowski(a, b):
    """Convex Minkowski sum via sorted edge directions, linear-size output."""
    a = np.roll(a, -np.lexsort((a[:, 0], a[:, 1]))[0], axis=0)
    b = np.roll(b, -np.lexsort((b[:, 0], b[:, 1]))[0], axis=0)
    edges = np.concatenate([np.roll(a, -1, axis=0) - a, np.roll(b, -1, axis=0) - b])
    angles = np.arctan2(edges[:, 1], edges[:, 0]) % (2 * np.pi)
    order = np.argsort(angles, kind="stable")
    start = a[0] + b[0]
    return _convex(np.concatenate([start[None, :], start + np.cumsum(edges[order], axis=0)[:-1]]))


def _buffer(polygon, distance):
    """Conservative circular offset, bounded by a circumscribed 32-sided disk.

    Axis extrema equal distance exactly. Unlike a miter offset, acute airfoil
    tips cannot produce arbitrarily long spikes. Radial overestimate is <0.5%.
    """
    if not distance:
        return polygon.copy()
    angles = (np.arange(32) + 0.5) * (2 * np.pi / 32)
    disk = np.column_stack((np.cos(angles), np.sin(angles))) * (distance / np.cos(np.pi / 32))
    return _minkowski(polygon, disk)


def _rotate(points, degrees):
    angle = math.radians(degrees)
    return np.asarray(points) @ np.array([[math.cos(angle), math.sin(angle)], [-math.sin(angle), math.cos(angle)]])


def _inventory(parts_dir: Path):
    root = Path(parts_dir).resolve()
    manifest_path = _safe_file(root, "manifest.json")
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest)
    if manifest.get("schema_version") != "1.0" or manifest.get("units", {}).get("geometry") != "mm":
        raise ValueError("Expected CAD manifest version 1.0 with geometry in mm")
    if not isinstance(manifest.get("parts"), list) or not manifest["parts"]:
        raise ValueError("Inventory must contain parts")
    hashes = manifest.get("file_sha256", {})
    names, paths, meshes, rows = set(), set(), {}, []
    for row in manifest["parts"]:
        name = row.get("part")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or name in names:
            raise ValueError(f"Invalid or duplicate part identifier: {name}")
        names.add(name)
        relative = row.get("files", {}).get("stl")
        path = _safe_file(root, relative)
        if path.suffix.lower() != ".stl" or relative in paths:
            raise ValueError(f"Invalid or duplicate STL path: {relative}")
        paths.add(relative)
        raw = path.read_bytes()
        expected = hashes.get(relative)
        if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected) or _sha(raw) != expected:
            raise ValueError(f"STL checksum mismatch or missing hash: {relative}")
        mesh = _triangles(raw, name)
        points = mesh.reshape(-1, 3)
        low, high = points.min(axis=0), points.max(axis=0)
        if abs(low[2]) > 0.1:
            raise ValueError(f"STL is not grounded in its canonical print orientation: {name}")
        settings = row.get("settings")
        if not isinstance(settings, dict) or not settings or not isinstance(row.get("profile"), str):
            raise ValueError(f"Missing print profile/settings: {name}")
        # JSON encoding also rejects NaN/Infinity hidden in settings.
        json.dumps(settings, allow_nan=False, sort_keys=True)
        rows.append({"part": name, "stl": relative, "stl_sha256": expected,
                     "profile": row["profile"], "material": row.get("material", settings.get("material", "")),
                     "settings": settings, "mass_estimate_g": _number(row.get("mass_g"), f"{name} mass"),
                     "bounds_mm": {"min": low.tolist(), "max": high.tolist()},
                     "size_mm": (high - low).tolist(), "triangle_count": len(mesh),
                     "footprint_polygon_mm": _convex(points[:, :2]).tolist(),
                     "notes": row.get("notes", [])})
        meshes[name] = mesh
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".stl"}
    if actual != paths:
        raise ValueError("Inventory STL files do not match the exact manifest part set")
    rows.sort(key=lambda r: r["part"])
    inventory = {"schema_version": "1.0", "manifest_sha256": _sha(raw_manifest),
                 "result_signature": manifest.get("result_signature"), "source_printer": manifest.get("printer", {}),
                 "part_count": len(rows), "mass_estimate_g": sum(r["mass_estimate_g"] for r in rows), "parts": rows}
    return inventory, meshes


def load_inventory(parts_dir: Path) -> dict:
    """Read and verify every source STL, returning JSON-safe inventory metadata."""
    return _inventory(parts_dir)[0]


def normalize_project(project: dict) -> dict:
    """Validate planning settings and fill defaults without changing the caller."""
    if project.get("schema_version") != "1.0" or not isinstance(project.get("name"), str) or not project["name"]:
        raise ValueError("Project requires schema_version 1.0 and a name")
    printer = project.get("printer", {})
    bed = printer.get("bed_mm", [])
    if len(bed) != 3:
        raise ValueError("printer.bed_mm must contain X, Y and Z")
    bed = [_number(x, "bed dimension", positive=True) for x in bed]
    _number(printer.get("nozzle_diameter_mm"), "nozzle diameter", positive=True)
    layout = project.get("layout", {})
    values = {k: _number(layout.get(k, default), k)
              for k, default in [("bed_margin_mm", 5), ("part_spacing_mm", 5),
                                 ("process_clearance_mm", 8)]}
    threshold = layout.get("single_part_above_height_mm")
    values["single_part_above_height_mm"] = (None if threshold is None else
                                           _number(threshold, "single_part_above_height_mm", positive=True))
    if 2 * values["bed_margin_mm"] >= min(bed[:2]):
        raise ValueError("Bed margin consumes the printable area")
    normalized = json.loads(json.dumps(project, allow_nan=False))
    normalized["layout"] = values
    normalized["printer"]["bed_mm"] = bed
    return normalized


def _variants(row, halo, usable):
    polygon = np.asarray(row["footprint_polygon_mm"])
    # Supplement a 10-degree grid with minimum-area rectangle axes. The latter
    # efficiently aligns narrow elevons without sacrificing the wing's diagonal fit.
    edges = np.roll(polygon, -1, axis=0) - polygon
    edge_angles = (-np.degrees(np.arctan2(edges[:, 1], edges[:, 0]))) % 180
    best_angle = min(edge_angles, key=lambda a: float(np.prod(np.ptp(_rotate(polygon, a), axis=0))))
    angles = sorted(set(range(0, 360, 10)) | {round(float((best_angle + a) % 360), 8) for a in (0, 90, 180, 270)})
    variants = []
    for angle in angles:
        raw = _rotate(polygon, angle)
        reserve = _buffer(raw, halo)
        minimum, maximum = reserve.min(axis=0), reserve.max(axis=0)
        size = maximum - minimum
        if np.all(size <= usable + 1e-7):
            variants.append({"angle": angle, "raw": raw - minimum, "reserve": reserve - minimum,
                             "minimum": minimum, "size": size})
    if not variants:
        raise ValueError(f"Part plus process clearance does not fit the bed: {row['part']}")
    return variants


def _cross(a, b):
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def _intersections(a, b):
    """All boundary intersections between two convex polygons."""
    av, bv = np.roll(a, -1, axis=0) - a, np.roll(b, -1, axis=0) - b
    difference = b[None, :, :] - a[:, None, :]
    divisor = _cross(av[:, None, :], bv[None, :, :])
    safe = np.where(abs(divisor) > 1e-10, divisor, np.nan)
    t = _cross(difference, bv[None, :, :]) / safe
    u = _cross(difference, av[:, None, :]) / safe
    valid = (t >= -1e-8) & (t <= 1 + 1e-8) & (u >= -1e-8) & (u <= 1 + 1e-8)
    i, j = np.nonzero(valid)
    return a[i] + t[i, j, None] * av[i]


def _inside(points, polygon):
    edges = np.roll(polygon, -1, axis=0) - polygon
    # Counter-clockwise convex hulls: strict interior is left of every edge.
    return np.all(_cross(edges[None, :, :], points[:, None, :] - polygon[None, :, :]) > 1e-7, axis=1)


def _position(variant, placed, usable, gap, axis):
    limit = usable - variant["size"]
    frame = np.array([[0., 0.], [limit[0], 0.], limit, [0., limit[1]]])
    nofit = []
    candidates = [frame]
    for previous in placed:
        # Origins inside A (+ spacing) minus B would violate separation.
        expanded = _buffer(previous["reserve"], gap)
        nfp = _minkowski(expanded, -variant["reserve"])
        candidates.extend([nfp, _intersections(nfp, frame)])
        nofit.append(nfp)
    # Contact between two existing parts can create feasible corners absent from
    # either original no-fit polygon's vertices.
    for i, a in enumerate(nofit):
        for b in nofit[i + 1:]:
            candidates.append(_intersections(a, b))
    points = np.concatenate(candidates)
    points = points[np.all(points >= -1e-7, axis=1) & np.all(points <= limit + 1e-7, axis=1)]
    for polygon in nofit:
        points = points[~_inside(points, polygon)]
        if not len(points):
            return None
    if not len(points):
        return None
    # Prefer a low strip, then left alignment, while considering both shelf axes
    # across independent search passes. All contact points are geometric, not a grid.
    order = np.lexsort((points[:, 1 - axis], points[:, axis]))
    return points[order[0]]


def _pack_group(rows, variants, usable, gap, tall, order, axis):
    bins = []
    for row in sorted(rows, key=order):
        isolated = tall is not None and row["size_mm"][2] > tall
        chosen = None
        if not isolated:
            for index, bin_ in enumerate(bins):
                if bin_["isolated"]:
                    continue
                for variant in variants[row["part"]]:
                    position = _position(variant, bin_["placed"], usable, gap, axis)
                    if position is None:
                        continue
                    extent = position + variant["size"]
                    score = (index, extent[axis], extent[1-axis], position[axis], position[1-axis], variant["angle"])
                    if chosen is None or score < chosen[0]:
                        chosen = score, bin_, variant, position
                if chosen is not None:
                    break  # backfill the earliest compatible bed before adding one
        if chosen is None:
            variant = min(variants[row["part"]], key=lambda v: (v["size"][axis], v["size"][1-axis], v["angle"]))
            bin_ = {"placed": [], "isolated": isolated}
            bins.append(bin_)
            chosen = None, bin_, variant, np.zeros(2)
        _, bin_, variant, position = chosen
        bin_["placed"].append({"row": row, "variant": variant, "position": position,
                               "reserve": variant["reserve"] + position})
    return bins


def _repair_pairs(bins, variants, usable, gap):
    """Repair a common greedy trap: two singles plus one pair can be two pairs.

    This bounded augmenting-path search reevaluates both orientations instead of
    keeping an early greedy pairing forever. Four opposing-corner arrangements
    per angle pair are deterministic and cheap for narrow aircraft panels.
    """
    cache = {}

    def pair(a, b):
        key = tuple(sorted((a["part"], b["part"])))
        if key in cache:
            return cache[key]
        for av in variants[a["part"]]:
            alimit = usable - av["size"]
            for bv in variants[b["part"]]:
                blimit = usable - bv["size"]
                for corner in (np.array([0., 0.]), np.array([1., 1.]), np.array([0., 1.]), np.array([1., 0.])):
                    apos, bpos = alimit * corner, blimit * (1 - corner)
                    aa, bb = av["reserve"] + apos, bv["reserve"] + bpos
                    # A zero distance also describes intersecting polygons. With
                    # zero configured gap, keep a microscopic positive separation
                    # during this optional repair instead of accepting overlaps.
                    if _polygon_distance(aa, bb) >= max(gap, 1e-6) - 1e-7:
                        result = {"isolated": False, "placed": [
                            {"row": a, "variant": av, "position": apos, "reserve": aa},
                            {"row": b, "variant": bv, "position": bpos, "reserve": bb}]}
                        cache[key] = result
                        return result
        cache[key] = None
        return None

    while True:
        singles = [i for i, b in enumerate(bins) if len(b["placed"]) == 1 and not b["isolated"]]
        pairs = [i for i, b in enumerate(bins) if len(b["placed"]) == 2 and not b["isolated"]]
        replacement = None
        for x, i in enumerate(singles):
            for j in singles[x + 1:]:
                a, b = bins[i]["placed"][0]["row"], bins[j]["placed"][0]["row"]
                for k in pairs:
                    c, d = (p["row"] for p in bins[k]["placed"])
                    for first, second in ((c, d), (d, c)):
                        ac = pair(a, first)
                        if ac is None:
                            continue
                        bd = pair(b, second)
                        if bd is not None:
                            replacement = {i, j, k}, [ac, bd]
                            break
                    if replacement:
                        break
                if replacement:
                    break
            if replacement:
                break
        if replacement is None:
            return bins
        removed, added = replacement
        bins = [b for i, b in enumerate(bins) if i not in removed] + added


def _arrange(inventory: dict, project: dict) -> list:
    bed_x, bed_y, max_z = project["printer"]["bed_mm"]
    layout = project["layout"]
    margin, gap, halo, tall = (layout[k] for k in ("bed_margin_mm", "part_spacing_mm", "process_clearance_mm", "single_part_above_height_mm"))
    usable = np.array([bed_x - 2 * margin, bed_y - 2 * margin])
    groups, variants = {}, {}
    for row in inventory["parts"]:
        if row["size_mm"][2] > max_z + 1e-6:
            raise ValueError(f"Part exceeds printer height: {row['part']}")
        key = json.dumps({k: row[k] for k in ("profile", "material", "settings")}, sort_keys=True)
        groups.setdefault(key, []).append(row)
        variants[row["part"]] = _variants(row, halo, usable)
    plates = []
    for key in sorted(groups):
        rows = groups[key]
        area = {r["part"]: _area(np.asarray(r["footprint_polygon_mm"])) for r in rows}
        orders = [lambda r: (-area[r["part"]], r["part"]),
                  lambda r: (-max(r["size_mm"][:2]), r["part"]),
                  lambda r: (area[r["part"]], r["part"])]
        lower_bound = math.ceil(sum(_area(variants[r["part"]][0]["reserve"]) for r in rows) / np.prod(usable) - 1e-10)
        best = None
        for order in orders:
            for axis in (1, 0):
                bins = _pack_group(rows, variants, usable, gap, tall, order, axis)
                if best is None or len(bins) < len(best):
                    best = bins
                if len(best) == lower_bound:
                    break
            if len(best) == lower_bound:
                break
        best = _repair_pairs(best, variants, usable, gap)
        for bin_ in best:
            first = bin_["placed"][0]["row"]
            plate = {"id": f"plate_{len(plates)+1:03d}", "profile": first["profile"], "material": first["material"],
                     "settings": first["settings"], "placements": []}
            for item in bin_["placed"]:
                row, variant = item["row"], item["variant"]
                position = item["position"] + margin
                raw, reserve = variant["raw"] + position, variant["reserve"] + position
                low, high = raw.min(axis=0), raw.max(axis=0)
                rlow, rhigh = reserve.min(axis=0), reserve.max(axis=0)
                translation = np.r_[position - variant["minimum"], -row["bounds_mm"]["min"][2]]
                plate["placements"].append({**row, "rotation_z_deg": variant["angle"], "translation_mm": translation.tolist(),
                    "placed_polygon_mm": raw.tolist(), "reserved_polygon_mm": reserve.tolist(),
                    "placed_bounds_mm": {"min": [*low, 0.0], "max": [*high, row["size_mm"][2]]},
                    "reserved_bounds_mm": {"min": rlow.tolist(), "max": rhigh.tolist()}})
            plate["mass_estimate_g"] = sum(p["mass_estimate_g"] for p in plate["placements"])
            plate["files"] = {"3mf": plate["id"] + ".3mf", "svg": plate["id"] + ".svg"}
            plates.append(plate)
    return plates


def _polygon_distance(a, b):
    """Euclidean separation of convex polygons, independent of no-fit packing."""
    a, b = np.asarray(a), np.asarray(b)
    edges = np.concatenate([np.roll(a, -1, axis=0) - a, np.roll(b, -1, axis=0) - b])
    normals = np.column_stack((-edges[:, 1], edges[:, 0]))
    projections_a, projections_b = a @ normals.T, b @ normals.T
    gaps = np.maximum(projections_a.min(axis=0) - projections_b.max(axis=0),
                      projections_b.min(axis=0) - projections_a.max(axis=0))
    if np.all(gaps <= 1e-10):
        return 0.0

    def point_to_edges(points, polygon):
        start, edge = polygon, np.roll(polygon, -1, axis=0) - polygon
        delta = points[:, None, :] - start[None, :, :]
        fraction = np.sum(delta * edge[None, :, :], axis=2) / np.sum(edge * edge, axis=1)
        closest = start[None, :, :] + np.clip(fraction, 0, 1)[..., None] * edge[None, :, :]
        return float(np.min(np.linalg.norm(points[:, None, :] - closest, axis=2)))

    return min(point_to_edges(a, b), point_to_edges(b, a))


def _validate_layout(plates, inventory, project):
    """Fail closed on missing parts, changed orientation, collision or clearance."""
    names = [p["part"] for plate in plates for p in plate["placements"]]
    if sorted(names) != sorted(p["part"] for p in inventory["parts"]):
        raise ValueError("Print layout does not cover every source part exactly once")
    layout, bed = project["layout"], np.array(project["printer"]["bed_mm"])
    margin, halo, gap = (layout[k] for k in ("bed_margin_mm", "process_clearance_mm", "part_spacing_mm"))
    for plate in plates:
        for i, p in enumerate(plate["placements"]):
            if any(p[key] != plate[key] for key in ("profile", "material", "settings")):
                raise ValueError("Incompatible print profiles share a bed")
            actual = _rotate(np.asarray(p["footprint_polygon_mm"]), p["rotation_z_deg"]) + np.array(p["translation_mm"][:2])
            if not np.allclose(actual, p["placed_polygon_mm"], atol=1e-7, rtol=0):
                raise ValueError("Placed footprint does not match the source transform")
            if (np.any(actual.min(axis=0) < margin + halo - 1e-6)
                    or np.any(actual.max(axis=0) > bed[:2] - margin - halo + 1e-6)
                    or p["size_mm"][2] > bed[2] + 1e-6):
                raise ValueError("Placed part or process clearance leaves the printer volume")
            for q in plate["placements"][i+1:]:
                if _polygon_distance(actual, q["placed_polygon_mm"]) < 2 * halo + gap - 1e-6:
                    raise ValueError("Placed parts violate process clearance or spacing")


def _outline(mesh):
    """Convex projection for preview only; no rounding touches exported geometry."""
    from ..fab.printer import _hull_2d
    return _hull_2d(mesh.reshape(-1, 3)[:, :2])


def _preview(plate, bed, outlines):
    width, height = bed[:2]
    tags = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"><rect width="{width}" height="{height}" fill="#f5f7fb" stroke="#333"/>']
    for number, p in enumerate(plate["placements"], 1):
        reserved_points = " ".join(f"{x:.4f},{height-y:.4f}" for x, y in p["reserved_polygon_mm"])
        tags.append(f'<polygon points="{reserved_points}" fill="#e5effc" stroke="#85a2c7" stroke-width="0.5" stroke-dasharray="2 1"/>')
        points = " ".join(f"{x:.4f},{height-y:.4f}" for x, y in outlines[p["part"]])
        tags.append(f'<polygon points="{points}" fill="#a9ccee" stroke="#315a87" stroke-width="0.5"><title>{html.escape(p["part"])}</title></polygon>')
        lo, hi = p["placed_bounds_mm"]["min"], p["placed_bounds_mm"]["max"]
        cx, cy = (lo[0] + hi[0]) / 2, height - (lo[1] + hi[1]) / 2
        tags.append(f'<circle cx="{cx}" cy="{cy}" r="5" fill="white" fill-opacity="0.94" stroke="#315a87" stroke-width="0.4"/>')
        tags.append(f'<text x="{cx}" y="{cy+2.4}" text-anchor="middle" font-family="sans-serif" font-size="7" font-weight="700" fill="#18384f">{number}</text>')
    tags.append(f'<text x="{width/2}" y="{height-1}" text-anchor="middle" font-family="sans-serif" font-size="3.5" fill="#4b6175">FRONT · X →</text>')
    return "".join(tags) + "</svg>\n"


def _queue(plan):
    blocks = []
    bed = plan["project"]["printer"]["bed_mm"]
    for number, plate in enumerate(plan["plates"], 1):
        settings = plate["settings"]
        parts = "".join(f'<li><span class="part-number">{i}</span><span>{html.escape(p["part"])}</span></li>'
                        for i, p in enumerate(plate["placements"], 1))
        infill = (f'{100 * float(settings["infill_fraction"]):g}% {settings.get("infill", "")}'
                  if "infill_fraction" in settings else "Confirm in slicer")
        rows = [("Walls", str(settings.get("perimeters", "Confirm"))),
                ("Width / layer", f'{settings.get("extrusion_width_mm", "—")} / {settings.get("layer_height_mm", "—")} mm'),
                ("Infill", infill), ("Supports", str(settings.get("supports", "Confirm in slicer")))]
        table = "".join(f'<tr><th scope="row">{label}</th><td>{html.escape(value)}</td></tr>' for label, value in rows)
        profile = html.escape(plate["profile"].replace("_", " ").capitalize())
        blocks.append(
            f'<article><div class="card-heading"><h2>Bed {number:02d}</h2><span class="profile">{profile}</span></div>'
            f'<p class="material">{html.escape(plate["material"])}</p>'
            f'<figure><img src="{plate["files"]["svg"]}" alt="Bed {number}: numbered part footprints and reserved process clearances">'
            f'<figcaption>{bed[0]:g} × {bed[1]:g} mm bed · {plate["mass_estimate_g"]:.1f} g CAD estimate</figcaption></figure>'
            f'<ul class="parts">{parts}</ul><table>{table}</table>'
            f'<a class="download" href="{plate["files"]["3mf"]}" download>Download bed 3MF <span aria-hidden="true">↓</span></a>'
            f'<details><summary>Full profile settings</summary><pre>{html.escape(json.dumps(settings, indent=2))}</pre></details></article>')
    title = "Survey wing — print bed review"
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
*{{box-sizing:border-box}}body{{font:15px/1.5 system-ui,sans-serif;color:#18384f;background:#edf2f6;margin:0}}
main{{max-width:1240px;margin:auto;padding:40px 24px}}h1{{font-size:clamp(25px,4vw,38px);line-height:1.15;margin:12px 0}}
.eyebrow{{color:#50718a;font-size:12px;font-weight:700;letter-spacing:.09em;text-transform:uppercase}}
.badge{{display:inline-block;background:#fff1d4;color:#805416;border:1px solid #e8d2a9;border-radius:20px;padding:4px 11px;font-size:12px;font-weight:700}}
.summary{{font-size:18px;color:#3f5c70;margin:12px 0 22px}}.review-note{{background:#fff;border-left:4px solid #3176a3;padding:16px 20px;border-radius:4px;max-width:920px}}
.review-note p{{margin:0 0 8px}}.review-note p:last-child{{margin-bottom:0}}.legend{{font-size:13px;color:#526d7e}}
.plan-link{{display:block;margin:18px 0 28px;color:#185c89;text-underline-offset:3px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,330px),1fr));gap:22px;align-items:start}}
article{{background:#fff;border:1px solid #d9e3eb;border-radius:12px;padding:18px;min-width:0;box-shadow:0 2px 5px #16344906}}
.card-heading{{display:flex;justify-content:space-between;gap:10px;align-items:center}}h2{{font-size:19px;margin:0;white-space:nowrap}}
.profile{{font-size:12px;background:#edf3f7;border-radius:5px;padding:3px 8px;color:#3f5c70}}.material{{font-size:13px;color:#536b7c;margin:6px 0 14px;overflow-wrap:anywhere}}
figure{{margin:0}}img{{display:block;width:100%;height:auto;border-radius:4px}}figcaption{{font-size:12px;color:#607786;margin:7px 0 12px}}
.parts{{list-style:none;padding:0;margin:0 0 12px}}.parts li{{display:flex;align-items:baseline;gap:7px;font:12px/1.6 ui-monospace,monospace;overflow-wrap:anywhere;margin:3px 0}}
.part-number{{flex:none;display:inline-block;text-align:center;border:1px solid #b5c8d6;border-radius:50%;width:18px;height:18px;font:11px/17px system-ui}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin:8px 0 15px}}th,td{{padding:5px 0;border-top:1px solid #e9eff3;text-align:left;vertical-align:top}}th{{font-weight:500;color:#677d8c;width:38%}}
.download{{display:flex;justify-content:space-between;background:#235f89;color:white;padding:10px 12px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:650}}
.download:hover{{background:#154b72}}details{{margin-top:12px;font-size:12px;color:#627a8b}}summary{{cursor:pointer}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f8;padding:10px;border-radius:4px}}
@media(max-width:600px){{main{{padding:24px 14px}}.summary{{font-size:16px}}}}
</style></head><body><main>
<header><div class="eyebrow">Prepared for your final check</div><h1>{title}</h1><span class="badge">Arranged geometry · Not sliced</span>
<p class="summary"><strong>{plan["part_count"]} parts</strong> · <strong>{len(plan["plates"])} beds</strong> · <strong>{plan["mass_estimate_g"]/1000:.2f} kg</strong> estimated printed mass</p></header>
<div class="review-note"><p><strong>Your approval comes before printing.</strong> Review these layouts, then open each bed 3MF in PrusaSlicer to check the printer, material, supports, brim and toolpaths. This package does not send or start a print.</p>
<p class="legend">Blue outlines show convex projections of the parts; dashed outlines reserve process clearance. Numbers match the part list. Mass excludes supports, brim and waste; print time and actual filament usage follow slicing.</p></div>
<a class="plan-link" href="print_plan.json">View plan and source provenance →</a>
<section class="grid" aria-label="Print bed layouts">{"".join(blocks)}</section>
</main></body></html>\n'''


def export_plan(parts_dir: Path, project: dict, output_dir: Path) -> dict:
    """Publish arranged plates atomically; never overwrite source geometry."""
    parts, out = Path(parts_dir).resolve(), Path(output_dir).resolve()
    if parts == out or parts in out.parents or out in parts.parents:
        raise ValueError("Print-plan output must be separate from its CAD input directory")
    if out.exists() and (not out.is_dir() or not (out / "print_plan.json").is_file()):
        raise ValueError("Refusing to replace an unrecognized print-plan output")
    project = normalize_project(project)
    inventory, meshes = _inventory(parts)
    plan = {"schema_version": "1.0", "artifact_state": "arranged_geometry", "sliced": False,
            "project": project, "manifest_sha256": inventory["manifest_sha256"], "result_signature": inventory["result_signature"],
            "part_count": inventory["part_count"], "mass_estimate_g": inventory["mass_estimate_g"],
            "estimates_exclude": ["brim", "supports", "purge", "failed prints"],
            "outstanding_validation": ["Exact printer and nozzle installed", "Manufacturer material preset and LW-ASA foaming calibration", "Support and brim extents fit reserved process clearance", "Slicer collision and toolpath preview", "Slicer print time and filament estimate"],
            "optimization": {"algorithm": "convex_no_fit_multiheuristic_v1", "rotation_grid_deg": 10,
                             "additional_rotations": "minimum-area rectangle axes", "orderings": 3,
                             "packing_axes": 2, "global_optimum_claimed": False},
            "plates": _arrange(inventory, project)}
    _validate_layout(plan["plates"], inventory, project)
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    backup = out.with_name(f".{out.name}-previous")
    try:
        for plate in plan["plates"]:
            objects = []
            outlines = {}
            for placement in plate["placements"]:
                mesh = meshes[placement["part"]].copy()
                mesh[..., :2] = _rotate(mesh[..., :2], placement["rotation_z_deg"])
                mesh += np.array(placement["translation_mm"])
                objects.append((placement["part"], mesh))
                outlines[placement["part"]] = _outline(mesh)
            write_plate(stage / plate["files"]["3mf"], objects, plate["id"])
            (stage / plate["files"]["svg"]).write_text(_preview(plate, project["printer"]["bed_mm"], outlines))
        (stage / "queue.html").write_text(_queue(plan))
        plan["file_sha256"] = {p.name: _sha(p.read_bytes()) for p in sorted(stage.iterdir())}
        (stage / "print_plan.json").write_text(json.dumps(plan, indent=2, allow_nan=False) + "\n")
        if load_inventory(parts) != inventory:
            raise ValueError("Source inventory changed while arranging plates")
        if backup.exists():
            raise ValueError("A previous print-plan backup exists; inspect it before replacing")
        if out.exists():
            out.rename(backup)
        try:
            stage.rename(out)
        except BaseException:
            if backup.exists():
                backup.rename(out)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return plan
    finally:
        if stage.exists():
            shutil.rmtree(stage)
