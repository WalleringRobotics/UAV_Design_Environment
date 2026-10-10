"""Build a self-contained review package from the actual CAD result and input files."""
from __future__ import annotations

import csv
import hashlib
import html
import importlib.metadata
import json
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path

from . import design as D


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bom_rows(d, config):
    """Electronics and payload inventory. No duplicated compute or pack mass."""
    rows = []
    def add(key, c, group, qty=1, mass=None):
        quantity = c.get("qty", qty)
        rows.append(dict(item=key, part=c.get("part", key), quantity=quantity,
                         unit_mass_g=c.get("mass_g", 0) if mass is None else mass,
                         total_mass_g=quantity*(c.get("mass_g", 0) if mass is None else mass),
                         group=group, rail=c.get("rail", "see wiring schedule"),
                         typical_power_w=quantity*c.get("power_w", 0),
                         source=c.get("source", ""), provenance=c.get("provenance", ""),
                         upstream_verified=c.get("verified", False),
                         confirm=c.get("confirm", "") or ("" if c.get("verified") else "Confirm exact SKU, mass and operating limits"),
                         unit_cost_eur="", cost_status="quote required"))
    for key, c in d.electronics.components.items():
        add(key, c, c.get("group", "avionics"))
    pl = d.payloads[config]
    for key, c in pl.cage_members.items():
        add(f"payload:{key}", c, "payload cage")
    for key, c in pl.tray.items():
        add(f"payload:{key}", c, "payload tray")
    add("payload:compute", pl.compute, f"compute:{config}")
    p = d.electronics.pack
    s = d.electronics.spec["pack"]
    add("battery:cells", {"part": s["cell"], "source": s.get("cell_source", ""),
                         "provenance": s.get("provenance", "")}, "battery", qty=p.cells, mass=p.cell_mass_g)
    add("battery:assembly", {"part": "Pack interconnect, connector, balancing lead, insulation",
                             "confirm": "Assembly mass allowance; qualify interconnect resistance and pack current"},
        "battery", mass=p.mass_g-p.cells*p.cell_mass_g)
    return rows


def _csv(path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def validate_cad_export(result, parts):
    from .fab.build import result_signature, verify_design_snapshot
    verify_design_snapshot(result.design)
    manifest = json.loads((parts / "manifest.json").read_text())
    if manifest.get("result_signature") != result_signature(result):
        raise ValueError("CAD export is stale: it does not describe this design result")
    names = {bp.name for bp in result.parts}
    required = {"assembly.step"} | {f"{ext}/{n}.{ext}" for ext in ("step", "stl") for n in names}
    if set(manifest.get("file_sha256", {})) != required:
        raise ValueError("CAD manifest must hash the complete and exact artifact set")
    actual = {str(p.relative_to(parts)) for p in parts.rglob("*")
              if p.is_file() and p.suffix.lower() in (".step", ".stl")}
    if actual != required:
        raise ValueError(f"CAD file set does not match manifest: missing={sorted(required - actual)}, unexpected={sorted(actual - required)}")
    for relative, expected in manifest.get("file_sha256", {}).items():
        path = (parts / relative).resolve()
        if not path.is_relative_to(parts) or not path.is_file() or sha256(path) != expected:
            raise ValueError(f"CAD export checksum mismatch: {relative}")


def export_review(result, out_dir, parts_dir):
    """Export only after successful CAD; stage replacements to avoid stale mixtures."""
    d = result.design
    root = D.REPO_ROOT
    out, parts = Path(out_dir).resolve(), Path(parts_dir).resolve()
    archive = out.with_suffix(".zip")
    if out == parts or out in parts.parents or parts in out.parents:
        raise ValueError("Review and CAD directories must be separate")
    if archive == out or archive == parts or archive in parts.parents or parts in archive.parents:
        raise ValueError("ZIP path must be separate from review and CAD directories")
    if archive.exists() and not archive.is_file():
        raise ValueError("ZIP destination must be a file")
    if not (parts / "manifest.json").exists():
        raise ValueError("Export CAD first")
    validate_cad_export(result, parts)
    expected_kg = d.evaluations[result.payload_config].auw_kg
    if abs(result.balance.auw_g / (expected_kg * 1000) - 1) >= 0.01:
        raise ValueError("Review package requires sizing and CAD balance within 1%; converge first")
    if out.exists() and any(out.iterdir()) and not (out / "release_manifest.json").exists():
        raise ValueError(f"Refusing to overwrite unrecognized output: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".review-", dir=out.parent))
    temporary = None
    try:
        shutil.copytree(parts, stage / "mechanical")
        (stage / "electronics").mkdir()
        for config in d.payloads:
            _csv(stage / "electronics" / f"bom_{config}.csv", bom_rows(d, config))
        trees = {c: d.electronics.power_tree(D.payload_loads_w(p)) for c,p in d.payloads.items()}
        (stage / "electronics" / "power_budget.json").write_text(json.dumps(trees, indent=2))
        peak_trees = {c: d.electronics.power_tree(D.payload_loads_w(p), peak=True) for c,p in d.payloads.items()}
        (stage / "electronics" / "peak_power_budget.json").write_text(json.dumps(peak_trees, indent=2))
        inputs = [*sorted((root / "platforms" / "survey_wing").glob("*.yaml")),
                  root / "payload" / "survey_cage.yaml", root / "mission" / "mission_params.yaml"]
        for source in inputs:
            dest = stage / "inputs" / source.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        for name in ("software_spec.md", "survey_wing.md", "critical_review.md", "hardware_spec.md"):
            source = root / "docs" / name
            if not source.exists():
                raise FileNotFoundError(source)
            shutil.copy2(source, stage / name)
        shutil.copy2(root / "requirements-lock.txt", stage / "requirements-lock.txt")
        from .integration import export_integration
        summary = {"selected": d.selected.summary(), "balance": result.balance.summary(),
                   "evaluations": {c: asdict(e) for c,e in d.evaluations.items()},
                   "printed_mass_g": result.printed_mass_g,
                   "geometry": D.airframe_geometry(d), "calibration": d.calibration,
                   "propulsion_screening": D.propulsion_checks(d), "thermal": D.thermal_report(d),
                   "survey_wind": D.survey_wind_report(d),
                   "launch_trade": D.launch_trade(d), "battery_trade": D.battery_trade(d),
                   "balance_alternatives": D.balance_alternatives(d, result.balance.summary())}
        export_integration(stage / "software", design_summary=summary)
        (stage / "design_summary.json").write_text(json.dumps(summary, indent=2, default=lambda o: float(o)))
        open_items = d.electronics.open_items()
        for config,p in d.payloads.items():
            open_items.extend(f"{config}/{r['item']}: {r['confirm']}" for r in bom_rows(d, config) if r["confirm"])
        open_items = sorted(set(open_items))
        (stage / "electronics" / "open_items.txt").write_text("\n".join(open_items)+"\n")
        _write_index(stage, result, open_items, summary)
        report = ["# Engineering checks", "", "Computed from the same input revision as the CAD package. Values are model predictions, not physical validation.", ""]
        for title, values in (("Propulsion screening", summary["propulsion_screening"]),
                              ("Wind and image blur", summary["survey_wind"]),
                              ("Cooling requirement", summary["thermal"]),
                              ("Launch alternatives", summary["launch_trade"]),
                              ("Battery alternatives", summary["battery_trade"]),
                              ("Balance alternatives", summary["balance_alternatives"])):
            report.extend([f"## {title}", "", "```json", json.dumps(values, indent=2), "```", ""])
        (stage / "engineering_checks.md").write_text("\n".join(report))
        try:
            rev = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root, text=True).strip())
        except (OSError, subprocess.CalledProcessError):
            rev, dirty = "unavailable", True
        # Content hashes cover inputs AND implementation, even before a checkpoint commit.
        source_files = [*root.glob("uavdesign/**/*.py"), *root.glob("scripts/**/*.py"),
                        *root.glob("integration/**/*"), *root.glob("docs/*.md"),
                        root / "pyproject.toml", root / "requirements-lock.txt",
                        root / "environment.yml", root / "README.md",
                        root / ".github" / "workflows" / "ci.yml", *inputs]
        manifest = {"schema_version": "1.0", "platform": "survey_wing", "git_revision": rev,
                    "tracked_worktree_modified": dirty, "maturity": "engineering review",
                    "source_sha256": {str(p.relative_to(root)): sha256(p) for p in sorted(set(source_files)) if p.is_file() and "__pycache__" not in p.parts},
                    "dependencies": {name: importlib.metadata.version(name) for name in
                                     ("numpy", "scipy", "aerosandbox", "neuralfoil", "cadquery", "pyyaml")},
                    "files": {str(p.relative_to(stage)): {"sha256": sha256(p), "bytes": p.stat().st_size}
                              for p in sorted(stage.rglob("*")) if p.is_file()}}
        (stage / "release_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
        checksums = {**{k:v["sha256"] for k,v in manifest["files"].items()},
                     "release_manifest.json": sha256(stage / "release_manifest.json")}
        (stage / "SHA256SUMS").write_text("".join(f"{v}  {k}\n" for k,v in sorted(checksums.items())))
        with tempfile.NamedTemporaryFile(prefix=".review-", suffix=".zip", dir=out.parent, delete=False) as f:
            temporary = Path(f.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for p in sorted(stage.rglob("*")):
                if p.is_file(): z.write(p, p.relative_to(stage))
        # Recheck inputs after the final analytical trades and serialization.
        validate_cad_export(result, parts)
        _publish_pair(stage, out, temporary, archive)
        return {"directory": str(out), "archive": str(archive), "files": len(manifest["files"])}
    finally:
        if stage.exists(): shutil.rmtree(stage)
        if temporary is not None and temporary.exists(): temporary.unlink()


def _publish_pair(stage, out, temporary, archive):
    """Publish directory and ZIP together, restoring each moved old path on failure."""
    backup = out.with_name(f".{out.name}-previous")
    archive_backup = archive.with_suffix(".zip.previous")
    if backup.exists() or archive_backup.exists():
        raise ValueError("Inspect prior export backup before exporting")
    moved_out = moved_archive = published_out = published_archive = False
    try:
        if out.exists():
            out.rename(backup)
            moved_out = True
        if archive.exists():
            archive.rename(archive_backup)
            moved_archive = True
        stage.rename(out)
        published_out = True
        temporary.replace(archive)
        published_archive = True
    except BaseException:
        if published_out: shutil.rmtree(out)
        if published_archive: archive.unlink()
        if moved_out: backup.rename(out)
        if moved_archive: archive_backup.rename(archive)
        raise
    if moved_out: shutil.rmtree(backup)
    if moved_archive: archive_backup.unlink()


def _write_index(out, result, open_items, summary):
    d, b = result.design, result.balance
    rows = "".join(f"<tr><td>{html.escape(c)}</td><td>{e.auw_kg:.2f} kg</td><td>{e.endurance_min:.1f} min</td></tr>" for c,e in d.evaluations.items())
    links = [("mechanical/assembly.step", "Assembly STEP"), ("mechanical/PRINT_LIST.md", "Print list"),
             ("electronics/bom_orin.csv", "Orin BOM (CSV)"), ("electronics/bom_cm5.csv", "CM5 BOM (CSV)"),
             ("hardware_spec.md", "Dedicated hardware specification"), ("software_spec.md", "Mapping software specification"),
             ("critical_review.md", "Critical review"), ("survey_wing.md", "Build and assembly guide"),
             ("engineering_checks.md", "Engineering checks and trade results"),
             ("design_summary.json", "Design calculations"), ("release_manifest.json", "Provenance and checksums")]
    anchors = "".join(f'<li><a href="{u}">{t}</a></li>' for u,t in links)
    baseline = summary["propulsion_screening"]["checks"][2]
    wind = summary["survey_wind"]
    issues = [f"Baseline propeller screening predicts {baseline['full_throttle_current_a']:.1f} A at full voltage and requires {baseline['esc_required_with_headroom_a']:.1f} A including headroom; the selected ESC candidate is rated {baseline['esc_rating_a']:.0f} A, subject to cooling qualification.",
              f"Imaging permits about {wind['maximum_imaging_tailwind_m_s']:.1f} m/s tailwind at the modeled cruise airspeed; the mission wind bound is {wind['mission_max_wind_m_s']:.1f} m/s. Wind-aware survey planning is required.",
              "Larger packs and bungee launch are alternatives with separate launch/fit checks."]
    if not b.summary().get("target_cg_reachable", False):
        issues.append(f"The {b.target_static_margin:.0%} static-margin target is unreachable in the configured battery bays; achieved estimate is {b.static_margin:.1%}.")
    endurance_target = d.design["requirements"]["endurance_min"]
    if d.selected.endurance_min < endurance_target:
        issues.append(f"The sizing configuration estimates {d.selected.endurance_min:.1f} minutes of cruise endurance against a {endurance_target:g}-minute target; the target is not met by this candidate.")
    flags = "".join(f"<li>{html.escape(s)}</li>" for s in issues)
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Wallering survey wing — design review</title><style>
body{{font:17px/1.55 system-ui;max-width:1100px;margin:40px auto;padding:0 24px;color:#173040;background:#f6f8fa}}
h1{{font-size:38px}}a{{color:#006b82}}img{{width:100%;background:white;border-radius:12px}}td,th{{padding:10px 24px;border-bottom:1px solid #cad4da}}.note{{padding:18px;background:#fff0d1;border-radius:10px}}li{{margin:6px 0}}
</style><h1>Survey wing · engineering review</h1><p>New fixed-wing hardware with shared mapping software. Existing OAK/PX4 platform retained.</p>
<p class="note">Generated design artifacts for iteration. Physical fit, printed strength, cooling, propulsion and flight performance remain to be measured. Candidate BOM has {len(open_items)} confirmation entries; blank prices require quotes.</p>
<ul>{flags}</ul>
<img src="mechanical/preview_iso.png" alt="CAD assembly preview"><p>{d.selected.span_m:.2f} m span · {b.auw_g/1000:.2f} kg CAD mass estimate · {len(result.parts)} printed parts · static margin {b.static_margin:.1%}</p>
<table><tr><th>Compute option</th><th>Sizing mass</th><th>Estimated cruise endurance</th></tr>{rows}</table>
<p>Endurance is an analytic cruise estimate with the configured reserve; it is not a measured sortie duration.</p><ul>{anchors}</ul>
<img src="mechanical/preview_pod.png" alt="Pod interior"><p>Edit the packaged YAML inputs in the repository and rebuild to iterate.</p></html>'''
    (out / "index.html").write_text(page)
