"""Offline, hash-bound plate planning from an existing CAD artifact inventory.

The result is arranged geometry, not machine instructions. Mesh orientation is
preserved; only translations and optional 90-degree rotations about Z are used.
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
    values = {k: _number(layout.get(k, default), k, positive=k == "single_part_above_height_mm")
              for k, default in [("bed_margin_mm", 5), ("part_spacing_mm", 5),
                                 ("process_clearance_mm", 8), ("single_part_above_height_mm", 150)]}
    if 2 * values["bed_margin_mm"] >= min(bed[:2]):
        raise ValueError("Bed margin consumes the printable area")
    normalized = json.loads(json.dumps(project, allow_nan=False))
    normalized["layout"] = values
    normalized["printer"]["bed_mm"] = bed
    return normalized


def _arrange(inventory: dict, project: dict) -> list:
    bed_x, bed_y, max_z = project["printer"]["bed_mm"]
    layout = project["layout"]
    margin, gap, halo, tall = (layout[k] for k in ("bed_margin_mm", "part_spacing_mm", "process_clearance_mm", "single_part_above_height_mm"))
    usable_x, usable_y = bed_x - 2 * margin, bed_y - 2 * margin
    groups = {}
    for row in inventory["parts"]:
        key = json.dumps({k: row[k] for k in ("profile", "material", "settings")}, sort_keys=True)
        groups.setdefault(key, []).append(row)
    plates = []
    for key in sorted(groups):
        current = None
        # Largest footprints first makes the simple shelf packing deterministic.
        rows = sorted(groups[key], key=lambda r: (-int(r["size_mm"][2] > tall),
                                                  -r["size_mm"][0] * r["size_mm"][1], r["part"]))
        for row in rows:
            sx, sy, sz = row["size_mm"]
            if sz > max_z + 1e-6:
                raise ValueError(f"Part exceeds printer height: {row['part']}")
            choices = [(0, sx + 2 * halo, sy + 2 * halo), (90, sy + 2 * halo, sx + 2 * halo)]
            choices = [c for c in choices if c[1] <= usable_x + 1e-6 and c[2] <= usable_y + 1e-6]
            if not choices:
                raise ValueError(f"Part plus process clearance does not fit the bed: {row['part']}")
            isolated = sz > tall
            chosen = None
            if current is not None and not isolated:
                for rotation, width, height in choices:
                    if current["cursor_x"] + width <= usable_x + 1e-6 and current["cursor_y"] + height <= usable_y + 1e-6:
                        chosen = rotation, width, height
                        break
                if chosen is None:
                    new_y = current["cursor_y"] + current["row_height"] + gap
                    for rotation, width, height in choices:
                        if new_y + height <= usable_y + 1e-6:
                            current.update(cursor_x=0.0, cursor_y=new_y, row_height=0.0)
                            chosen = rotation, width, height
                            break
            if current is None or isolated or chosen is None:
                current = {"id": f"plate_{len(plates)+1:03d}", "profile": row["profile"], "material": row["material"],
                           "settings": row["settings"], "placements": [], "cursor_x": 0.0, "cursor_y": 0.0, "row_height": 0.0}
                plates.append(current)
                chosen = choices[0]
            rotation, width, height = chosen
            x, y = margin + current["cursor_x"], margin + current["cursor_y"]
            low, high = row["bounds_mm"]["min"], row["bounds_mm"]["max"]
            rotated_min = low if rotation == 0 else [-high[1], low[0], low[2]]
            translation = [x + halo - rotated_min[0], y + halo - rotated_min[1], -low[2]]
            current["placements"].append({**row, "rotation_z_deg": rotation, "translation_mm": translation,
                "placed_bounds_mm": {"min": [x + halo, y + halo, 0.0], "max": [x + width - halo, y + height - halo, sz]},
                "reserved_bounds_mm": {"min": [x, y], "max": [x + width, y + height]}})
            current["cursor_x"] += width + gap
            current["row_height"] = max(current["row_height"], height)
            if isolated:
                current = None
    for plate in plates:
        for key in ("cursor_x", "cursor_y", "row_height"):
            del plate[key]
        plate["mass_estimate_g"] = sum(p["mass_estimate_g"] for p in plate["placements"])
        plate["files"] = {"3mf": plate["id"] + ".3mf", "svg": plate["id"] + ".svg"}
    return plates


def _outline(mesh):
    """Convex projection for preview only; no rounding touches exported geometry."""
    from ..fab.printer import _hull_2d
    return _hull_2d(mesh.reshape(-1, 3)[:, :2])


def _preview(plate, bed, outlines):
    width, height = bed[:2]
    tags = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"><rect width="{width}" height="{height}" fill="#f5f7fb" stroke="#333"/>']
    for number, p in enumerate(plate["placements"], 1):
        bounds = p["reserved_bounds_mm"]
        lo, hi = bounds["min"], bounds["max"]
        tags.append(f'<rect x="{lo[0]}" y="{height-hi[1]}" width="{hi[0]-lo[0]}" height="{hi[1]-lo[1]}" fill="#e5effc" stroke="#85a2c7" stroke-width="0.5" stroke-dasharray="2 1"/>')
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
<p class="legend">Blue outlines show convex projections of the parts; dashed boxes reserve process clearance. Numbers match the part list. Mass excludes supports, brim and waste; print time and actual filament usage follow slicing.</p></div>
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
            "plates": _arrange(inventory, project)}
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    backup = out.with_name(f".{out.name}-previous")
    try:
        for plate in plan["plates"]:
            objects = []
            outlines = {}
            for placement in plate["placements"]:
                mesh = meshes[placement["part"]].copy()
                if placement["rotation_z_deg"] == 90:
                    mesh = mesh[..., [1, 0, 2]] * np.array([-1, 1, 1])
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
