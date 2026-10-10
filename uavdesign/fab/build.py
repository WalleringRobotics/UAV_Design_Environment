"""Design -> printable parts -> balance, in one call.

    from uavdesign.fab.build import build
    result = build(export_dir="outputs/parts")

1. Runs the design chain (:func:`uavdesign.design.run`) for the planform.
2. Builds every printed part (right side + mirrored left) with CadQuery.
3. Checks each part against the printer volume in its print orientation.
4. Computes printed mass and CG of each part (shell + infill model).
5. Places all bought-in items (payload, BOM, tubes) and solves the battery
   position for the design static margin.
6. Optionally exports print-oriented STLs, per-part and assembly STEP files,
   a JSON manifest and a Markdown print list.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import cadquery as cq
import numpy as np
import yaml

from .. import design as D
from ..payload import SurveyPayload
from ..structures import Tube
from . import parts as P
from .geometry import PodGeometry, WingGeometry, spar_layout
from .massprops import PrintedMass, printed_mass, settings_from_profile
from .printer import Fit, PrinterProfile, check_fit, orient_to_axis


@dataclass
class BuiltPart:
    part: P.Part
    fit: Fit
    mass: PrintedMass
    profile: dict

    @property
    def name(self) -> str:
        return self.part.name


@dataclass
class MassItem:
    name: str
    mass_g: float
    x_mm: float
    z_mm: float = 0.0
    group: str = ""


@dataclass
class Balance:
    items: list
    battery_x_mm: float
    battery_x_range: tuple
    cg_x_mm: float
    x_np_mm: float
    mac_mm: float
    static_margin: float
    target_static_margin: float
    auw_g: float
    contingency_g: float

    @property
    def battery_in_range(self) -> bool:
        lo, hi = self.battery_x_range
        return lo <= self.battery_x_mm <= hi

    def summary(self) -> dict:
        return {
            "auw_g": float(self.auw_g),
            "cg_x_mm": float(self.cg_x_mm),
            "x_np_mm": float(self.x_np_mm),
            "static_margin": float(self.static_margin),
            "target_static_margin": float(self.target_static_margin),
            "battery_x_mm": float(self.battery_x_mm),
            "battery_in_range": bool(self.battery_in_range),
        }


@dataclass
class BuildResult:
    design: D.Design
    fab: dict
    parts: list
    balance: Balance
    printed_mass_g: dict = field(default_factory=dict)
    exported: dict = field(default_factory=dict)

    @property
    def all_fit(self) -> bool:
        return all(bp.fit.fits for bp in self.parts)

    def part_table(self) -> list[dict]:
        rows = []
        for bp in self.parts:
            rows.append({
                "part": bp.name,
                "side": bp.part.side,
                "group": bp.part.group,
                "profile": bp.part.profile,
                "material": self.fab["materials"][bp.profile["material"]]["name"],
                "mass_g": round(bp.mass.mass_g, 1),
                "fits": bp.fit.fits,
                "footprint_mm": f"{bp.fit.footprint_mm[0]:.0f} x {bp.fit.footprint_mm[1]:.0f}",
                "height_mm": round(bp.fit.height_mm),
            })
        return rows


def load_fab(design: D.Design) -> dict:
    return yaml.safe_load((design.platform_dir / "fabrication.yaml").read_text())


# --------------------------------------------------------------------------- #
# Building
# --------------------------------------------------------------------------- #

def _vertices(shape, tol: float = 0.6) -> np.ndarray:
    v, _ = shape.tessellate(tol, 0.3)
    return np.array([[p.x, p.y, p.z] for p in v])


def build_parts(d: D.Design, fab: dict, config: str = "orin", progress=None):
    g = D.airframe_geometry(d)
    printer = PrinterProfile.from_dict(fab["printer"])
    w = WingGeometry.from_airframe(g, fab["wing"]["te_thickness_mm"])
    spars = spar_layout(w, g["spars"], g["pod_width_mm"] / 2)
    pod = PodGeometry.from_dict(fab["pod"])
    payload = d.payloads[config]

    def fit(part):
        return check_fit(_vertices(part.solid), printer, part.print_up)

    def say(msg):
        if progress:
            progress(msg)

    say("wing panel")
    right = P.build_wing_panel(w, spars, fab["wing"], g["pod_width_mm"] / 2, g["elevon_y_mm"],
                               g["elevon_chord_fraction"], fit)
    say("fin")
    right.append(P.build_fin(w, g["fin_area_mm2"], g["fin_height_mm"]))
    say("pod")
    centre = P.build_pod(w, spars, pod, fab["pod"], fab["layout"], fit)
    centre.extend(P.build_skid(pod, fab["pod"], fab["layout"]))
    say("cage + tray")
    centre.append(P.build_cage(pod, payload.cage_members, fab["layout"], payload.window_standoff_mm,
                               fab["pod"]["wall_mm"]))
    centre.append(P.build_tray(pod, fab["layout"], fab["pod"]["wall_mm"], float(spars.joiner.p0[0]) + 16))

    all_parts = right + [p.mirrored() for p in right] + centre
    built = []
    for p in all_parts:
        prof = fab["profiles"][p.profile]
        settings = settings_from_profile(prof, fab["materials"])
        built.append(BuiltPart(p, fit(p), printed_mass(p.solid, settings), prof))
    return built, w, spars, pod


# --------------------------------------------------------------------------- #
# Balance
# --------------------------------------------------------------------------- #

def mass_items(d: D.Design, fab: dict, built: list, w: WingGeometry, spars, pod: PodGeometry,
               config: str) -> list[MassItem]:
    items = [MassItem(bp.name, bp.mass.mass_g, float(bp.mass.cg_mm[0]), float(bp.mass.cg_mm[2]), "printed")
             for bp in built]
    lay = fab["layout"]
    pos = lay["positions"]
    pl: SurveyPayload = d.payloads[config]

    # Survey cage members, in cage coordinates offset to the lens axis / window
    xcam = lay["cage_lens_axis_x_mm"]
    z0 = pod.bottom_z(xcam) + fab["pod"]["wall_mm"] + pl.window_standoff_mm
    for k, m in pl.cage_members.items():
        p = np.asarray(m["position_mm"], float) + [0, 0, m["envelope_mm"][2] / 2]
        items.append(MassItem(f"payload:{k}", m["mass_g"], xcam + p[0], z0 + p[2], "payload"))
    items.append(MassItem("payload:compute", pl.compute["mass_g"], *pos["compute"], "payload"))
    items.append(MassItem("payload:nvme", pl.tray["nvme"]["mass_g"], *pos["nvme"], "payload"))
    items.append(MassItem("payload:harness", pl.tray["harness"]["mass_g"], *pos["payload_harness"], "payload"))

    # Electronics BOM
    fw = fab["wing"]
    e0, e1 = D.airframe_geometry(d)["elevon_y_mm"]
    ys = e0 + 0.25 * (e1 - e0)
    servo_pt = w.point_at(ys, fw["servo_x_over_c"])
    for k, c in d.electronics.components.items():
        m = c["qty"] * c["mass_g"]
        if k == "servo_elevon":
            items.append(MassItem(k, m, float(servo_pt[0]), float(servo_pt[2]), c.get("group", "")))
        else:
            x, z = pos[k]
            items.append(MassItem(k, m, x, z, c.get("group", "")))

    # Carbon tubes
    sp = d.design["structure"]["spars"]

    def tube(dct):
        return Tube(dct["od_mm"], dct["id_mm"], sp["density_g_cm3"])

    j, o, rp = spars.joiner, spars.outer, spars.rear_pin
    items.append(MassItem("tube:joiner", tube(sp["joiner"]).mass_g(j.length_mm), float(j.p0[0]), float(j.p0[2]), "tubes"))
    items.append(MassItem("tube:sleeves", 2 * tube(sp["sleeve"]).mass_g(spars.sleeve.length_mm),
                          float(spars.sleeve.p0[0]), float(spars.sleeve.p0[2]), "tubes"))
    mid = 0.5 * (o.p0 + o.p1)
    items.append(MassItem("tube:outer_spars", 2 * tube(sp["outer_spar"]).mass_g(o.length_mm), float(mid[0]), float(mid[2]), "tubes"))
    half_in = pod.at(float(rp.p0[0]))["w"] / 2 - fab["pod"]["wall_mm"]
    rp_len = 2 * (sp["rear_pin"]["half_length_mm"] - (half_in - 16))
    items.append(MassItem("tube:rear_pins", tube(sp["rear_pin"]).mass_g(rp_len), float(rp.p0[0]), float(rp.p0[2]), "tubes"))
    items.append(MassItem("hardware", d.design["structure"]["hardware_mass_g"], *pos["hardware"], "hardware"))
    return items


def solve_balance(d: D.Design, fab: dict, items: list[MassItem]) -> Balance:
    pack_g = d.electronics.pack.mass_g
    m = sum(i.mass_g for i in items)
    mom = sum(i.mass_g * i.x_mm for i in items)
    target_sm = d.design["planform"]["static_margin"]
    x_np, mac = d.stability.x_np_mm, d.stability.mac_mm
    x_cg = x_np - target_sm * mac
    x_batt = (x_cg * (m + pack_g) - mom) / pack_g
    bays = [tuple(b) for b in fab["layout"]["battery_bays_mm"]]
    candidates = [float(np.clip(x_batt, lo, hi)) for lo, hi in bays]
    x_b = min(candidates, key=lambda c: abs(c - x_batt))
    lo, hi = next(b for b, c in zip(bays, candidates) if c == x_b)
    cg = (mom + pack_g * x_b) / (m + pack_g)
    contingency = d.design["contingency_fraction"] * (m - sum(i.mass_g for i in items if i.group == "payload"))
    all_items = items + [MassItem("battery", pack_g, x_b, -60.0, "battery")]
    return Balance(all_items, x_b, (lo, hi), cg, x_np, mac, (x_np - cg) / mac, target_sm,
                   m + pack_g + contingency, contingency)


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #

def print_oriented(bp: BuiltPart, printer: PrinterProfile) -> cq.Shape:
    """Rotate so print_up is +Z, apply the fitting rotation, sit on the bed centre."""
    up = np.asarray(bp.part.print_up, float)
    up = up / np.linalg.norm(up)
    z = np.array([0.0, 0.0, 1.0])
    s = bp.part.solid
    axis = np.cross(up, z)
    if np.linalg.norm(axis) < 1e-9:
        if up[2] < 0:
            s = s.rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), 180.0)
    else:
        ang = math.degrees(math.acos(float(np.clip(np.dot(up, z), -1, 1))))
        s = s.rotate(cq.Vector(0, 0, 0), cq.Vector(*axis), ang)
    s = s.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), bp.fit.angle_deg)
    bb = s.BoundingBox()
    cx, cy = printer.bed_x_mm / 2, printer.bed_y_mm / 2
    return s.translate(cq.Vector(cx - (bb.xmin + bb.xmax) / 2, cy - (bb.ymin + bb.ymax) / 2, -bb.zmin))


def export(result: BuildResult, out_dir: str | Path, stl_tolerance: float = 0.05) -> dict:
    out = Path(out_dir)
    (out / "stl").mkdir(parents=True, exist_ok=True)
    (out / "step").mkdir(parents=True, exist_ok=True)
    printer = PrinterProfile.from_dict(result.fab["printer"])
    files = {}
    for bp in result.parts:
        stl = out / "stl" / f"{bp.name}.stl"
        cq.exporters.export(print_oriented(bp, printer), str(stl), tolerance=stl_tolerance, angularTolerance=0.1)
        step = out / "step" / f"{bp.name}.step"
        cq.exporters.export(bp.part.solid, str(step))
        files[bp.name] = {"stl": str(stl.relative_to(out)), "step": str(step.relative_to(out))}
    asm = cq.Compound.makeCompound([bp.part.solid for bp in result.parts])
    cq.exporters.export(asm, str(out / "assembly.step"))
    files["_assembly"] = "assembly.step"

    manifest = {
        "printer": result.fab["printer"],
        "design": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in D.airframe_geometry(result.design).items()
                   if not isinstance(v, dict)},
        "balance": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in result.balance.summary().items()},
        "printed_mass_g": {k: round(v, 1) for k, v in result.printed_mass_g.items()},
        "parts": [
            {**row, "files": files[row["part"]], "notes": bp.part.notes,
             "settings": {k: v for k, v in bp.profile.items()}}
            for row, bp in zip(result.part_table(), result.parts)
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=_jsonable))
    (out / "PRINT_LIST.md").write_text(print_list_markdown(result))
    result.exported = files
    return files


def _jsonable(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o).__name__)


def print_list_markdown(result: BuildResult) -> str:
    fab = result.fab
    lines = [
        f"# Print list — {fab['printer']['name']}",
        "",
        "Generated by `scripts/build_parts.py`. STLs are already oriented for printing and centred on the bed;",
        "import into PrusaSlicer, pick the material profile, then apply the settings column.",
        "",
        "| Part | Material | Settings | Orientation | Footprint (mm) | Height | Est. mass |",
        "|---|---|---|---|---|---|---|",
    ]
    for bp in result.parts:
        pr = bp.profile
        mat = fab["materials"][pr["material"]]["name"]
        st = f"{pr['perimeters']} perim · {int(pr['infill_fraction'] * 100)}% {pr.get('infill', '')} · {pr['layer_height_mm']} mm"
        lines.append(f"| {bp.name} | {mat} | {st} | {pr.get('orientation', '')} | "
                     f"{bp.fit.footprint_mm[0]:.0f} × {bp.fit.footprint_mm[1]:.0f} | {bp.fit.height_mm:.0f} | {bp.mass.mass_g:.0f} g |")
    tot = sum(bp.mass.mass_g for bp in result.parts)
    lines += ["", f"**Total printed mass: {tot:.0f} g** across {len(result.parts)} parts.", "",
              "## Materials", ""]
    for k, m in fab["materials"].items():
        used = sum(bp.mass.mass_g for bp in result.parts if bp.profile["material"] == k)
        if used:
            lines.append(f"- **{m['name']}** — {used:.0f} g. {m.get('note', '')}")
    lines += ["", "## Assembly notes", ""]
    seen = set()
    for bp in result.parts:
        for n in bp.part.notes:
            if (bp.part.name.rstrip("_LR"), n) not in seen:
                seen.add((bp.part.name.rstrip("_LR"), n))
                lines.append(f"- `{bp.name}`: {n}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CAD -> sizing calibration
# --------------------------------------------------------------------------- #

def calibration_from(result: BuildResult) -> dict:
    """New correction factors so the analytic structure model matches the CAD.

    factor_new = factor_used * CAD / analytic(with factor_used), per group.
    """
    d = result.design
    m = d.selected.masses_g
    cal = dict(d.calibration)
    wing_cad = result.printed_mass_g.get("wing", 0.0)
    wing_an = m["struct_wing_panels"] + m["struct_fins"]
    pod_cad = result.printed_mass_g.get("pod", 0.0)
    pod_an = m["struct_pod"]
    cage = next(bp.mass.mass_g for bp in result.parts if bp.name == "survey_cage")
    return {
        "wing_mass_factor": round(float(cal.get("wing_mass_factor", 1.0)) * wing_cad / wing_an, 4),
        "pod_mass_factor": round(float(cal.get("pod_mass_factor", 1.0)) * pod_cad / pod_an, 4),
        "cage_structure_g": round(float(cage), 1),
        "measured": {
            "wing_printed_g": round(wing_cad, 1),
            "pod_printed_g": round(pod_cad, 1),
            "cage_printed_g": round(float(cage), 1),
            "auw_balance_g": round(float(result.balance.auw_g), 1),
            "auw_sizing_g": round(d.selected.auw_kg * 1000, 1),
        },
    }


def write_calibration(cal: dict, platform_dir: Path) -> Path:
    path = platform_dir / "calibration.yaml"
    header = ("# GENERATED by scripts/build_parts.py — CAD-measured corrections fed back into\n"
              "# the sizing loop (uavdesign.design.run reads this file). Do not edit by hand.\n")
    path.write_text(header + yaml.safe_dump(cal, sort_keys=False))
    return path


def converge(platform: str = "survey_wing", config: str = "orin", max_iter: int = 4, tol: float = 0.01,
             progress=None) -> tuple[BuildResult, list]:
    """Iterate design <-> CAD until the sizing AUW and the CAD factors stop moving."""
    history = []
    cal = None
    result = None
    for it in range(1, max_iter + 1):
        d = D.run(platform, calibration=cal)
        if progress:
            progress(f"iteration {it}: sizing AUW {d.selected.auw_kg:.3f} kg, span {d.selected.span_m:.3f} m")
        result = build(platform, config, design=d, progress=progress)
        new = calibration_from(result)
        history.append({"iteration": it, "auw_sizing_kg": d.selected.auw_kg, "span_m": d.selected.span_m,
                        **{k: v for k, v in new.items() if k != "measured"}, **new["measured"]})
        old = cal or {"wing_mass_factor": 1.0, "pod_mass_factor": 1.0}
        dw = abs(new["wing_mass_factor"] - old.get("wing_mass_factor", 1.0)) / new["wing_mass_factor"]
        dp = abs(new["pod_mass_factor"] - old.get("pod_mass_factor", 1.0)) / new["pod_mass_factor"]
        cal = new
        if cal is not None and it > 1 and dw < tol and dp < tol:
            break
    write_calibration(cal, result.design.platform_dir)
    return result, history


# --------------------------------------------------------------------------- #
# Top level
# --------------------------------------------------------------------------- #

def build(platform: str = "survey_wing", config: str = "orin", export_dir: str | Path | None = None,
          design: D.Design | None = None, progress=None) -> BuildResult:
    d = design or D.run(platform)
    fab = load_fab(d)
    built, w, spars, pod = build_parts(d, fab, config, progress)
    items = mass_items(d, fab, built, w, spars, pod, config)
    bal = solve_balance(d, fab, items)
    groups = {}
    for bp in built:
        groups[bp.part.group] = groups.get(bp.part.group, 0.0) + bp.mass.mass_g
    res = BuildResult(d, fab, built, bal, groups)
    if export_dir:
        export(res, export_dir)
    return res
