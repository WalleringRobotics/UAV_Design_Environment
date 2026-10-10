"""Reproducible review drawings from exported STEP, with explicit evidence levels.

The STEP files contain assembled aircraft coordinates; print-oriented STL must
never be used to infer aircraft dimensions. PNGs are depth-buffered CAD renders.
SVGs preserve vector labels and embed those same raster views, so the files are
self-contained and do not imply more tessellation precision than the PNGs.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import yaml

from .render import _camera, _mesh, _rasterize, _vertex_light

INK = "#193445"
MUTED = "#586e7c"
COLOURS = {"wing_skin": "#9aafbb", "elevon": "#59a2a2", "fin": "#608aa8",
           "pod_shell": "#9da9b4", "hatch": "#c4a67a", "structural": "#607c8d", "skid": "#6b936c"}
VIEWS = {"top": (90, 0), "side": (0, -90), "front": (0, 180), "iso": (26, -125)}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass
class _Part:
    row: dict
    solid: object
    vertices: np.ndarray
    triangles: np.ndarray
    brightness: np.ndarray
    colour: str
    lower: np.ndarray
    upper: np.ndarray

    @property
    def name(self):
        return self.row["part"]

    def shifted(self, xyz):
        return replace(self, vertices=self.vertices + xyz,
                       lower=self.lower + xyz, upper=self.upper + xyz)


def _checked_sources(parts_dir, summary_path):
    """Fail closed on mixed, modified or escaping source artifacts."""
    parts_dir, summary_path = Path(parts_dir).resolve(), Path(summary_path).resolve()
    manifest_path = parts_dir / "manifest.json"
    manifest_bytes, summary_bytes = manifest_path.read_bytes(), summary_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    summary = json.loads(summary_bytes)
    rows = manifest.get("parts", [])
    names = [p["part"] for p in rows]
    if not names or len(set(names)) != len(names):
        raise ValueError("Expected a nonempty, uniquely named CAD part set")
    sources = {"mechanical/manifest.json": hashlib.sha256(manifest_bytes).hexdigest(),
               "design_summary.json": hashlib.sha256(summary_bytes).hexdigest()}
    for row in rows:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", row["part"]):
            raise ValueError("Unsafe CAD part identifier")
        relative = row["files"]["step"]
        if relative != f"step/{row['part']}.step":
            raise ValueError("STEP source must match its part identifier")
        path = (parts_dir / relative).resolve()
        expected = manifest.get("file_sha256", {}).get(relative)
        if not path.is_relative_to(parts_dir) or not path.is_file() or _sha(path) != expected:
            raise ValueError(f"CAD source checksum mismatch: {relative}")
        sources[f"mechanical/{relative}"] = expected
    for key in ("auw_g", "cg_x_mm", "x_np_mm", "battery_x_mm", "battery_z_mm"):
        if not np.isclose(summary["balance"][key], manifest["balance"][key], rtol=0, atol=1e-6):
            raise ValueError(f"Summary and CAD balance differ: {key}")
    for key in ("root_chord_mm", "tip_chord_mm", "half_span_mm"):
        if not np.isclose(summary["geometry"][key], manifest["design"][key], rtol=0, atol=0.001):
            raise ValueError(f"Summary and CAD geometry differ: {key}")
    return manifest, summary, sources


def _load_parts(parts_dir, manifest):
    import cadquery as cq

    parts = []
    for row in manifest["parts"]:
        solid = cq.importers.importStep(str(parts_dir / row["files"]["step"])).val()
        if not solid.isValid() or not solid.Solids():
            raise ValueError(f"Invalid STEP solid: {row['part']}")
        vertices, triangles = _mesh(solid, 0.8)
        if not len(triangles) or not np.all(np.isfinite(vertices)):
            raise ValueError(f"Undrawable STEP solid: {row['part']}")
        lower, upper = _brep_bounds(solid)
        parts.append(_Part(row, solid, vertices, triangles, _vertex_light(vertices, triangles),
                           "#d28a37" if row["group"] == "payload" else COLOURS.get(row["profile"], "#99aabb"),
                           lower, upper))
    return parts


def _brep_bounds(solid):
    """Ignore cached triangulation, which otherwise enlarges OCC bounds."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(solid.wrapped, box, False, False)
    values = np.asarray(box.Get())
    return values[:3], values[3:]


def _bounds(parts):
    return np.min([p.lower for p in parts], axis=0), np.max([p.upper for p in parts], axis=0)


def _render(ax, parts, view="iso", width=1400, padding=0.035):
    """Render actual triangles with a depth buffer; return the projection matrix."""
    camera = _camera(VIEWS[view] if isinstance(view, str) else view)
    meshes = [(p.vertices @ camera, p) for p in parts]
    xy = np.vstack([v[:, :2] for v, _ in meshes])
    lo, hi = xy.min(0), xy.max(0)
    span = np.maximum(hi - lo, 1.0)
    lo, hi = lo - span * padding, hi + span * padding
    scale = width / (hi[0] - lo[0])
    height = max(8, int(np.ceil((hi[1] - lo[1]) * scale)))
    # Very tall thin parts should not create unbounded images.
    if height > 2200:
        scale *= 2200 / height
        width = max(8, int(np.ceil(width * 2200 / height)))
        height = 2200
    pixels = np.full((height, width, 3), 255, dtype=np.uint8)
    depth = np.full((height, width), -np.inf, dtype=np.float32)
    for points, part in meshes:
        screen = points.copy()
        screen[:, 0] = (points[:, 0] - lo[0]) * scale
        screen[:, 1] = (hi[1] - points[:, 1]) * scale
        _rasterize(screen, part.triangles, part.brightness, part.colour, pixels, depth)
    ax.imshow(pixels, extent=(lo[0], hi[0], lo[1], hi[1]), origin="upper", interpolation="antialiased")
    ax.set_aspect("equal")
    ax.tick_params(labelsize=8, colors=MUTED)
    for spine in ax.spines.values():
        spine.set_color("#d1dbe0")
    return camera


def _style(fig, title, subtitle, footer):
    fig.patch.set_facecolor("white")
    fig.suptitle(title, x=0.045, y=0.97, ha="left", fontsize=21, fontweight="bold", color=INK)
    fig.text(0.045, 0.923, subtitle, fontsize=10, color=MUTED, va="top")
    fig.text(0.045, 0.025, footer, fontsize=8, color=MUTED, va="bottom")


def _save(fig, out, key, title, caption, files):
    for ext in ("png", "svg"):
        path = out / f"{key}.{ext}"
        with matplotlib.rc_context({"svg.hashsalt": f"uavdesign-review-{key}"}):
            fig.savefig(path, dpi=170, facecolor="white",
                        metadata={"Creator": "uavdesign.fab.review_views", "Date": None} if ext == "svg" else None)
    plt.close(fig)
    files.append({"id": key, "title": title, "caption": caption,
                  "files": {ext: f"{key}.{ext}" for ext in ("png", "svg")}})


def _dimension(ax, a, b, label, vertical=False):
    ax.annotate("", xy=b, xytext=a, arrowprops={"arrowstyle": "|-|", "color": INK, "lw": 1.1})
    midpoint = (np.asarray(a) + b) / 2
    ax.annotate(label, midpoint, xytext=(9, 0) if vertical else (0, -14),
                textcoords="offset points", ha="left" if vertical else "center", va="center", fontsize=9, color=INK,
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.5})


def _three_view(parts, summary, out, files):
    lo, hi = _bounds(parts)
    size = hi - lo
    fig = plt.figure(figsize=(15, 11))
    grid = fig.add_gridspec(2, 2, height_ratios=(1.65, 1), width_ratios=(1, 1), left=0.07, right=0.95,
                          top=0.85, bottom=0.14, hspace=0.55, wspace=0.23)
    top, side, front = fig.add_subplot(grid[0, :]), fig.add_subplot(grid[1, 0]), fig.add_subplot(grid[1, 1])
    _render(top, parts, "top")
    top.set_title("TOP · nose upward", loc="left", color=INK, fontsize=12)
    top.set_xlabel("y · right from centreline [mm]", fontsize=9)
    top.set_ylabel("−x · forward [mm]", fontsize=9)
    _dimension(top, (lo[1], -hi[0]-95), (hi[1], -hi[0]-95), f"Printed span {size[1]:.1f} mm")
    top.set_ylim(-hi[0]-145, -lo[0]+100)
    top.axhline(0, color=MUTED, lw=0.6, ls=":")
    top.annotate("Wing root leading-edge datum (x = 0)", (0, 0), xytext=(180, 160),
                 arrowprops={"arrowstyle": "-", "color": MUTED}, fontsize=8, color=MUTED)
    _render(side, parts, "side", width=900)
    side.set_title("SIDE · looking toward +y", loc="left", color=INK, fontsize=12)
    side.set_xlabel("x · aft of wing root LE [mm]", fontsize=9)
    side.set_ylabel("z · up [mm]", fontsize=9)
    _dimension(side, (lo[0], lo[2]-42), (hi[0], lo[2]-42), f"Printed length {size[0]:.1f} mm")
    _dimension(side, (hi[0]+55, lo[2]), (hi[0]+55, hi[2]), f"{size[2]:.1f} mm", vertical=True)
    side.set_ylim(lo[2]-95, hi[2]+70)
    side.set_xlim(lo[0]-45, hi[0]+180)
    _render(front, parts, "front", width=1100)
    front.set_title("FRONT · looking aft (+x)", loc="left", color=INK, fontsize=12)
    front.set_xlabel("−y · left from centreline [mm]", fontsize=9)
    front.set_ylabel("z · up [mm]", fontsize=9)
    front.set_ylim(lo[2]-75, hi[2]+75)
    _style(fig, "Survey wing · dimensioned CAD views",
           "Assembled STEP geometry · millimetres · equal scale within each view; views use independent magnification",
           "Dimensions enclose printed parts, including fins and skids. Motor, propeller, antennas and other bought-in hardware are excluded.\n"
           f"Aerodynamic design span: {2*summary['geometry']['half_span_mm']:.1f} mm. STEP bounding boxes determine the printed extents; tessellation is for display only.")
    _save(fig, out, "airframe_three_view", "Dimensioned airframe views",
          "Orthographic top, side and front views of the exported assembled STEP parts. Dimensions are BREP bounding-box extents, not print-oriented STL dimensions.", files)


def _exploded(parts, out, files):
    shown, translations = [], {}
    for part in parts:
        row = part.row
        if row["group"] == "wing":
            delta = np.array([0, 240 if row["side"] == "R" else -240, 0])
        elif row["profile"] == "hatch":
            delta = np.array([0, 0, 240])
        elif row["group"] == "payload":
            delta = np.array([0, 0, 120])
        elif row["profile"] == "skid":
            delta = np.array([0, 0, -100])
        else:
            delta = np.zeros(3)
        shown.append(part.shifted(delta))
        translations[part.name] = delta.tolist()
    fig, ax = plt.subplots(figsize=(15, 10))
    fig.subplots_adjust(left=0.05, right=0.95, top=0.87, bottom=0.26)
    camera = _render(ax, shown, width=1850)
    ax.axis("off")
    groups = [("Right wing", lambda p:p.row["group"]=="wing" and p.row["side"]=="R", (60, 45)),
              ("Left wing", lambda p:p.row["group"]=="wing" and p.row["side"]=="L", (-85, -40)),
              ("Access hatches", lambda p:p.row["profile"]=="hatch", (65, 50)),
              ("Rigid survey cage", lambda p:p.row["group"]=="payload", (-125, 30)),
              ("Replaceable skids", lambda p:p.row["profile"]=="skid", (-65, -55)),
              ("Pod shells, joints and fitted trays", lambda p:p.name=="pod_tail", (90, -25))]
    for label, select, offset in groups:
        chosen = [p for p in shown if select(p)]
        if not chosen:
            continue
        low, high = _bounds(chosen)
        target = ((low+high)/2) @ camera
        ax.annotate(label, target[:2], xytext=offset, textcoords="offset points", fontsize=10,
                    ha="left" if offset[0]>0 else "right", color=INK,
                    bbox={"facecolor":"white", "edgecolor":"#ced8de", "boxstyle":"round,pad=0.35"},
                    arrowprops={"arrowstyle":"-", "color":MUTED})
    _style(fig, "Survey wing · assembly relationships",
           "Exploded display of the actual printed solids · exact part identifiers are on the segment map and catalogue",
           "Display offsets only: each wing moves 240 mm outward; hatches +240 mm z; cage +120 mm z; skids −100 mm z.\n"
           "These offsets are not assembly clearances or a removal sequence. Carbon tubes, dowels, fasteners and purchased electronics are absent from this printed-parts STEP assembly.")
    group_counts = Counter(p.row["group"] for p in parts)
    wing_counts = Counter(p.row["profile"] for p in parts if p.row["group"] == "wing")
    pod_counts = Counter(p.row["profile"] for p in parts if p.row["group"] == "pod")
    fig.text(.06, .17, f"{group_counts['wing']} wing parts", fontsize=15, fontweight="bold", color=INK)
    fig.text(.06, .125, f"{wing_counts['wing_skin']} skins · {wing_counts['elevon']} elevons · {wing_counts['structural']} covers · {wing_counts['fin']} fins", fontsize=10, color=MUTED)
    fig.text(.40, .17, f"{group_counts['pod']} pod parts", fontsize=15, fontweight="bold", color=INK)
    fig.text(.40, .125, f"{pod_counts['pod_shell']} shells / rings · {pod_counts['hatch']} hatches · {pod_counts['skid']} skids · {pod_counts['structural']} structural", fontsize=10, color=MUTED)
    fig.text(.77, .17, f"{group_counts['payload']} survey cage", fontsize=15, fontweight="bold", color=INK)
    fig.text(.77, .125, "Rigid camera + GNSS support", fontsize=10, color=MUTED)
    _save(fig, out, "exploded_assembly", "Exploded printed assembly",
          "Translated printed part families reveal assembly relationships. Translation vectors are recorded in views_manifest.json; neither hardware clearances nor disassembly access is validated by this picture.", files)
    return translations


def _hardware_envelopes(summary_path, summary, sources):
    """Read only packaged inputs: never silently substitute a current repo YAML."""
    base = summary_path.parent / "inputs"
    fab_path = base / "platforms/survey_wing/fabrication.yaml"
    payload_path = base / "payload/survey_cage.yaml"
    if not fab_path.is_file() or not payload_path.is_file():
        return []
    snapshots = {path: path.read_bytes() for path in (fab_path, payload_path)}
    for path, data in snapshots.items():
        sources[str(path.relative_to(summary_path.parent))] = hashlib.sha256(data).hexdigest()
    fab, payload = yaml.safe_load(snapshots[fab_path]), yaml.safe_load(snapshots[payload_path])
    from .geometry import PodGeometry
    pod = PodGeometry.from_dict(fab["pod"])
    layout = fab["layout"]
    xcam = layout["cage_lens_axis_x_mm"]
    z0 = pod.bottom_z(xcam) + fab["pod"]["wall_mm"] + payload["cage"]["window_standoff_mm"]
    envelopes = []
    for key, item in payload["cage"]["members"].items():
        size = np.asarray(item["envelope_mm"], dtype=float)
        centre = np.asarray(item["position_mm"], dtype=float) + [xcam, 0, z0+size[2]/2]
        envelopes.append({"id":key, "label":key.replace("_", " "), "centre_mm":centre.tolist(), "size_mm":size.tolist(),
                          "evidence":"declared package envelope; not a detailed or clearance-checked hardware model"})
    selected = summary.get("payload_config", "orin")
    # The heavy baseline is explicit in the current export; callers add the CAD payload configuration.
    compute = payload["compute"][selected]
    envelopes.append({"id":"compute", "label":f"compute ({selected})", "centre_mm":[layout["positions"]["compute"][0], 0, layout["positions"]["compute"][1]],
                      "size_mm":compute["envelope_mm"], "evidence":"declared compute enclosure envelope; connector and cooling clearance unverified"})
    bay = next(p for p in layout["battery_placements"] if p["name"]==summary["balance"]["battery_bay"])
    envelopes.append({"id":"battery", "label":"5S1P battery", "centre_mm":[summary["balance"]["battery_x_mm"],0,summary["balance"]["battery_z_mm"]],
                      "size_mm":bay["size_mm"], "evidence":"analytic pack envelope; real assembly and leads unmeasured"})
    return envelopes


def _cutaway(parts, summary, envelopes, out, files):
    import cadquery as cq
    selected = [p for p in parts if p.row["group"] != "wing"]
    keep = cq.Solid.makeBox(6000, 3000, 6000, cq.Vector(-3000, -3000, -3000))
    cut = []
    for part in selected:
        if part.row["profile"] in ("pod_shell", "hatch"):
            shape = part.solid.intersect(keep)
            vertices, triangles = _mesh(shape, 0.8)
            if not len(triangles):
                continue
            cut.append(replace(part, vertices=vertices, triangles=triangles, brightness=_vertex_light(vertices, triangles)))
        else:
            cut.append(part)
    fig, (iso, side) = plt.subplots(2,1,figsize=(15,12), gridspec_kw={"height_ratios":[1.1,1]})
    fig.subplots_adjust(left=.08,right=.94,top=.865,bottom=.13,hspace=.27)
    _render(iso,cut,view=(22,55),width=1500)
    iso.axis("off")
    iso.set_title("A · real printed CAD, +y shell and hatch halves removed",loc="left",fontsize=11,color=INK)
    _render(side,cut,"side",width=1500)
    side.set_title("B · side projection with declared hardware envelopes",loc="left",fontsize=11,color=INK)
    palette=["#bd6927","#b84741","#9162a6","#247775","#416a9b","#795641","#297748"]
    for index, env in enumerate(envelopes):
        x,y,z=env["centre_mm"]; dx,dy,dz=env["size_mm"]
        colour=palette[index%len(palette)]
        side.add_patch(Rectangle((x-dx/2,z-dz/2),dx,dz,fill=False,edgecolor=colour,lw=1.5,linestyle="--"))
        side.annotate(str(index+1),(x,z),ha="center",va="center",fontsize=8,color="white",
                      bbox={"facecolor":colour,"edgecolor":"none","boxstyle":"circle,pad=0.22"})
    low, high = _bounds(selected)
    envelope_low = [np.asarray(e["centre_mm"])-np.asarray(e["size_mm"])/2 for e in envelopes]
    envelope_high = [np.asarray(e["centre_mm"])+np.asarray(e["size_mm"])/2 for e in envelopes]
    if envelopes:
        low = np.minimum(low, np.min(envelope_low,axis=0))
        high = np.maximum(high, np.max(envelope_high,axis=0))
    side.set_xlim(low[0]-35,high[0]+35);side.set_ylim(low[2]-35,high[2]+35)
    side.set_xlabel("x · aft of wing root leading edge [mm]",fontsize=9);side.set_ylabel("z · up [mm]",fontsize=9)
    _style(fig,"Survey wing · pod and payload packaging",
           "Solid geometry: printed parts from STEP. Dashed boxes: analytical envelopes from the packaged configuration.",
           "Section display only; internal solids are retained. Overlap in a projected view is not proof of collision or clearance.\n"
           "Hardware envelopes exclude connector bend radii, wiring, thermal paths and mounting tolerances; physical integration remains open.")
    if envelopes:
        for index,env in enumerate(envelopes):
            fig.text(.065+(index%4)*.235,.087-(index//4)*.023,f"{index+1}  {env['label']}",color=palette[index%len(palette)],fontsize=9)
    else:
        fig.text(.08,.075,"Hardware envelope overlay unavailable: packaged fabrication/payload inputs absent.",color=MUTED,fontsize=9)
    _save(fig,out,"pod_cutaway","Pod cutaway and payload envelopes",
          "The +y halves of pod shells and hatches are removed by a CAD boolean for display. Dashed side-view envelopes are analytic assumptions from packaged YAML, not imported commercial component CAD or a clearance certification.",files)


def _segment_map(parts,out,files):
    wing=[p for p in parts if p.row["group"]=="wing" and p.row["side"]=="R"]
    if not wing:
        return
    fig=plt.figure(figsize=(15,10))
    ax=fig.add_axes((.065,.40,.87,.45))
    palette=plt.get_cmap("tab20")
    coloured=[replace(p,colour=matplotlib.colors.to_hex(palette(i%20))) for i,p in enumerate(wing)]
    camera=_render(ax,coloured,"top",width=1800)
    for i,part in enumerate(coloured):
        point=((part.lower+part.upper)/2) @ camera
        ax.annotate(str(i+1),point[:2],ha="center",va="center",fontsize=10,color=INK,
                    bbox={"facecolor":"white","edgecolor":part.colour,"boxstyle":"circle,pad=.25","linewidth":1.5})
    ax.set_xlabel("y · right from centreline [mm]",fontsize=9);ax.set_ylabel("−x · forward [mm]",fontsize=9)
    _style(fig,"Survey wing · printable segment map",
           "Right wing in assembled coordinates · index numbers resolve to the exact STEP/STL part identifiers below",
           "The left wing is mirrored. Each row names its left counterpart explicitly. Colours identify parts, not materials.\n"
           "Assembly seams come from the exported solids; dowels, glue, spar tubes and tape hinges require the build instructions and qualification.")
    for i,part in enumerate(coloured):
        col=i//6;row=i%6
        counterpart=part.name.replace("_R","_L")
        fig.text(.075+col*.48,.325-row*.041,f"{i+1:02d}   {part.name}   /   {counterpart}",fontsize=10,color=INK)
    _save(fig,out,"wing_segment_map","Wing segment and control-surface map",
          "Numbered right-wing CAD solids with exact left/right export identifiers. The skin split, separate elevons, fin and servo cover are visible without substituting schematic shapes.",files)


def _catalogue(parts,out,files):
    for page,start in enumerate(range(0,len(parts),21),1):
        selected=parts[start:start+21]
        fig,axes=plt.subplots(7,3,figsize=(15,19))
        fig.subplots_adjust(left=.045,right=.96,top=.88,bottom=.065,wspace=.12,hspace=.68)
        for ax,part in zip(axes.flat,selected):
            _render(ax,[part],"iso",width=480,padding=.08)
            ax.axis("off")
            ax.set_title(part.name,loc="left",fontsize=10,color=INK,pad=7)
            size=part.upper-part.lower
            ax.text(.0,-.11,f"{part.row['profile']} · {part.row['mass_g']:.1f} g estimated\n"
                    f"Assembly XYZ: {size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} mm",transform=ax.transAxes,
                    fontsize=8,color=MUTED,va="top")
        for ax in list(axes.flat)[len(selected):]:
            ax.axis("off")
        _style(fig,f"Survey wing · CAD part catalogue {page}",
               "Each picture is the named STEP solid · independent magnification · assembled orientation, not a print-bed layout",
               "XYZ dimensions use aircraft axes and exact STEP bounding boxes. Printed mass is the manifest estimate, before brims and supports.\n"
               "Open the named STEP for mechanical inspection, or its STL / arranged 3MF for print orientation. These views are not dimensioned manufacturing drawings.")
        _save(fig,out,f"part_catalogue_{page:02d}",f"CAD part catalogue {page}",
              "Individual actual CAD solids, exact artifact identifiers, estimated printed mass and assembled-axis bounding-box dimensions. Pictures use different scales and retain aircraft orientation.",files)


def export_review_views(parts_dir: Path, summary_path: Path, out_dir: Path) -> dict:
    """Write technical figures (PNG + self-contained SVG) and their manifest.

    ``summary_path.parent/inputs`` supplies optional packaged hardware envelopes.
    This function is intended to write into the review exporter's staging tree.
    It validates source checksums before rendering and rechecks them afterwards.
    """
    parts_dir,summary_path,out_dir=map(lambda p:Path(p).resolve(),(parts_dir,summary_path,out_dir))
    if (out_dir==parts_dir or out_dir in parts_dir.parents or parts_dir in out_dir.parents
            or out_dir==summary_path.parent):
        raise ValueError("View output must be separate from CAD and summary input directories")
    manifest,summary,sources=_checked_sources(parts_dir,summary_path)
    parts=_load_parts(parts_dir,manifest)
    lower,upper=_bounds(parts)
    out_dir.mkdir(parents=True,exist_ok=True)
    files=[]
    envelopes=_hardware_envelopes(summary_path,{**summary,"payload_config":manifest["payload_config"]},sources)
    _three_view(parts,summary,out_dir,files)
    offsets=_exploded(parts,out_dir,files)
    _cutaway(parts,summary,envelopes,out_dir,files)
    _segment_map(parts,out_dir,files)
    _catalogue(parts,out_dir,files)
    _,_,checked=_checked_sources(parts_dir,summary_path)
    if any(sources[key]!=value for key,value in checked.items()):
        raise ValueError("CAD or summary changed during drawing export")
    for relative,expected in sources.items():
        if relative.startswith("inputs/") and _sha(summary_path.parent/relative)!=expected:
            raise ValueError("Packaged hardware input changed during drawing export")
    result={"schema_version":"1.0","coordinate_frame":{"x":"aft from wing root leading edge","y":"right","z":"up","units":"mm"},
            "dimensions_mm":{"x_length":float(upper[0]-lower[0]),"y_span":float(upper[1]-lower[1]),"z_height":float(upper[2]-lower[2]),
                             "lower_xyz":lower.tolist(),"upper_xyz":upper.tolist(),"basis":"STEP BREP bounding boxes of printed parts only"},
            "part_count":len(parts),"figures":files,"source_sha256":sources,
            "source_locations":{"mechanical":os.path.relpath(parts_dir,out_dir),
                                "design_summary.json":os.path.relpath(summary_path,out_dir),
                                "inputs":os.path.relpath(summary_path.parent/"inputs",out_dir)},
            "renderer_sha256":{name:_sha(Path(__file__).with_name(name)) for name in (Path(__file__).name,"render.py","geometry.py")},
            "tessellation":{"cadquery_tolerance_parameter":.8,"relative_deflection":True,"angular_tolerance_rad":.35,"dimensions_use_tessellation":False},
            "exploded_offsets_mm":offsets,"hardware_envelopes":envelopes,
            "limitations":["Printed solid geometry only; bought-in hardware is absent except labelled analytical envelope overlays.",
                           "No fit, strength, aerodynamic, thermal or print-profile validation is implied by rendered appearance.",
                           "SVG files contain embedded depth-buffered raster geometry and vector labels."]}
    result["file_sha256"]={path.name:_sha(path) for path in sorted(out_dir.iterdir()) if path.suffix in (".png",".svg")}
    (out_dir/"views_manifest.json").write_text(json.dumps(result,indent=2)+"\n")
    return result
