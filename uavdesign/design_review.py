"""Execute and package an independently reviewable design, without printer access.

The snapshot is a runnable repository, not a collection of undocumented pictures.
Notebooks execute against that snapshot; failed execution or changed source never
replaces a previously published dossier. Generated evidence is distinguished from
physical validation throughout the package.
"""
from __future__ import annotations

import hashlib
import html
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlsplit
import zipfile

from .artifacts import _publish_pair, sha256


SOURCE_DIRS = ("uavdesign", "scripts", "tests", "platforms", "payload", "mission",
               "integration", "print_projects", "docs", ".github/workflows")
SOURCE_FILES = ("README.md", "pyproject.toml", "requirements.txt", "requirements-lock.txt",
                "environment.yml", ".gitignore")
SOURCE_SUFFIXES = {".py", ".yaml", ".yml", ".md", ".ipynb", ".json", ".toml", ".txt"}
STYLE = """
:root{color-scheme:light;font:17px/1.65 system-ui,sans-serif;color:#203d4f;background:#eef3f6}
*{box-sizing:border-box}body{max-width:1200px;margin:0 auto;padding:36px 30px 70px}
h1,h2,h3{line-height:1.18;color:#12344b}h1{font-size:clamp(32px,4vw,52px);letter-spacing:-1.5px}
h2{font-size:30px;margin-top:48px}h3{font-size:21px}a{color:#176287;text-underline-offset:3px}
nav{display:flex;gap:22px;flex-wrap:wrap;border-bottom:1px solid #b8cbd7;padding:16px 0}
.eyebrow{font-size:12px;letter-spacing:2px;text-transform:uppercase;font-weight:750;color:#426e87}
.lead{max-width:850px;font-size:20px}.note{background:#fff4d9;padding:18px 22px;border-left:4px solid #bc852c;border-radius:5px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:22px}
.card,.stat{background:#fff;border:1px solid #d5e0e7;border-radius:10px;padding:20px}
.card img{width:100%;height:240px;object-fit:contain;background:#fff}.card p{font-size:15px}
.stats{display:flex;gap:16px;flex-wrap:wrap}.stat{flex:1;min-width:170px}.stat strong{font-size:26px;display:block}
.hero{width:100%;max-height:570px;object-fit:contain;background:white;border-radius:12px;margin:24px 0}
table{border-collapse:collapse;width:100%;background:white;font-size:15px}td,th{padding:12px;text-align:left;border-bottom:1px solid #d5e0e7;vertical-align:top}
th{background:#e2edf3}.table-scroll{overflow-x:auto}pre{padding:18px;background:#e1eaf0;border-radius:6px;overflow:auto;font-size:13px}
code{font-size:.9em;overflow-wrap:anywhere}img{max-width:100%}blockquote{border-left:3px solid #8aaabb;padding-left:20px}
li{margin:7px 0}.muted{color:#567181;font-size:14px}.button{display:inline-block;background:#215f82;color:white;padding:10px 15px;border-radius:6px;text-decoration:none}
@media print{body{background:white;padding:0;max-width:none}.card,figure,pre{break-inside:avoid}nav{display:none}h2{break-after:avoid}}
"""


def _write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def source_snapshot(root: Path) -> dict[str, bytes]:
    """An explicit allowlist excludes credentials, Git state and local MCP config."""
    candidates = [root / name for name in SOURCE_FILES]
    for name in SOURCE_DIRS:
        directory = root / name
        if directory.is_symlink():
            raise ValueError(f"Source directory cannot be a symlink: {name}")
        if directory.exists():
            candidates.extend(p for p in directory.rglob("*")
                              if p.suffix in SOURCE_SUFFIXES and "__pycache__" not in p.parts
                              and ".ipynb_checkpoints" not in p.parts)
    snapshot = {}
    for path in sorted(set(candidates)):
        if path.is_symlink():
            raise ValueError(f"Source file cannot be a symlink: {path.relative_to(root)}")
        if path.is_file():
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Source escapes repository")
            snapshot[path.relative_to(root).as_posix()] = path.read_bytes()
    return snapshot


def _hashes(snapshot: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(data).hexdigest() for name, data in snapshot.items()}


def validate_release(directory: Path, source_hashes: dict) -> dict:
    """Require complete, untampered exports from the same source revision."""
    path = directory / "release_manifest.json"
    if not path.is_file():
        raise ValueError("Build outputs/review first with scripts/build_parts.py --review-out outputs/review")
    manifest = json.loads(path.read_text())
    entries = manifest.get("files", {})
    if not entries or not manifest.get("source_sha256"):
        raise ValueError("Release manifest lacks file/source provenance")
    expected = set(entries) | {"release_manifest.json", "SHA256SUMS"}
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    if actual != expected:
        raise ValueError("Release file set changed; rebuild outputs/review")
    for name, entry in entries.items():
        target = directory / name
        if (target.is_symlink() or not target.resolve().is_relative_to(directory.resolve())
                or sha256(target) != entry["sha256"]):
            raise ValueError(f"Release checksum mismatch: {name}")
    stale = [name for name, digest in manifest["source_sha256"].items()
             if source_hashes.get(name) != digest]
    if stale:
        raise ValueError("Release source changed; rebuild outputs/review: " + ", ".join(stale))
    return manifest


def _offline_html(document: str, original_dir: Path, destination_dir: Path, package: Path) -> str:
    """Keep notebook outputs/code, remove optional CDN scripts and resolve local links."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(document, "html.parser")
    rendered_markdown = {package / "source/README.md",
                         *(package / "source/docs").glob("*.md")}
    # All figures here are static outputs; no widget or remote JS runtime is required.
    for tag in soup.find_all("script"):
        tag.decompose()
    for tag in soup.find_all("link", href=True):
        if urlsplit(tag["href"]).netloc:
            tag.decompose()
    for tag in soup.find_all(["a", "img"]):
        key = "href" if tag.name == "a" else "src"
        if not tag.get(key):
            continue
        url = urlsplit(tag[key])
        if url.scheme or url.netloc or not url.path:
            continue
        target = (original_dir / unquote(url.path)).resolve()
        if target.is_relative_to(package.resolve()) and target.exists():
            if target in rendered_markdown and not tag.has_attr("download"):
                target = target.with_suffix(".html")
            if (target.suffix == ".ipynb" and target.parent == package / "source/platforms/survey_wing"
                    and not tag.has_attr("download")):
                executed = package / "notebooks" / target.with_suffix(".html").name
                if executed.exists():
                    target = executed
            relative = Path(os.path.relpath(target, destination_dir)).as_posix()
            tag[key] = relative + ("#" + url.fragment if url.fragment else "")
    return str(soup)


def _notebook_html(nb, source: Path, destination: Path, package: Path):
    from nbconvert import HTMLExporter

    exporter = HTMLExporter(template_name="classic", embed_images=True,
                            require_js_url="", mathjax_url="", jquery_url="")
    document, _ = exporter.from_notebook_node(nb, resources={
        "metadata": {"path": str(source.parent), "name": source.stem}})
    document = _offline_html(document, source.parent, destination.parent, package)
    banner = ('<div style="padding:18px 30px;background:#e7f0f5;font:16px system-ui">'
              '<a href="../index.html#notebooks">← Design review</a> · '
              'Executed analysis; values are model estimates, not flight measurements. '
              f'<a href="{destination.with_suffix(".ipynb").name}">Download notebook</a></div>')
    document = re.sub(r"(<body[^>]*>)", r"\1" + banner, document, count=1)
    destination.write_text(document)


def execute_notebooks(source_root: Path, destination: Path, *, progress=print) -> list[dict]:
    """Use a private kernel spec bound to the current interpreter, not a global kernel."""
    import nbformat
    from nbclient import NotebookClient
    from jupyter_client import KernelManager
    from jupyter_client.kernelspec import KernelSpecManager

    destination.mkdir(parents=True, exist_ok=True)
    records = []
    paths = sorted((source_root / "platforms/survey_wing").glob("*.ipynb"))
    if not paths:
        raise ValueError("No survey-wing notebooks found")
    with tempfile.TemporaryDirectory(prefix="uav-review-kernel-") as temp:
        kernels = Path(temp) / "kernels"
        kernel = kernels / "uav-review"
        kernel.mkdir(parents=True)
        _write_json(kernel / "kernel.json", {
            "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "display_name": "Design review snapshot", "language": "python"})
        env = dict(os.environ)
        # Jupyter and matplotlib must not rely on writable global/home directories.
        env.update({"MPLBACKEND": "Agg", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1", "MPLCONFIGDIR": str(Path(temp) / "mpl"),
                    "XDG_CACHE_HOME": str(Path(temp) / "cache")})
        for path in paths:
            progress(f"Executing {path.name}")
            nb = nbformat.read(path, as_version=4)
            for cell in nb.cells:
                if cell.cell_type == "code":
                    cell.outputs, cell.execution_count = [], None
            started = time.monotonic()
            limit = 180 if path.name.startswith("07_") else 60

            def deadline(**_):
                if time.monotonic() - started >= limit:
                    raise TimeoutError(f"{path.name} exceeded {limit}s whole-notebook limit")

            km = KernelManager(kernel_name="uav-review",
                               kernel_spec_manager=KernelSpecManager(kernel_dirs=[str(kernels)]))
            client = NotebookClient(nb, km=km, timeout=limit, allow_errors=False,
                                    on_cell_start=deadline,
                                    resources={"metadata": {"path": str(path.parent)}})
            try:
                client.execute(env=env)
            finally:
                # An explicitly supplied manager is not owned/closed by nbclient.
                if km.has_kernel:
                    km.shutdown_kernel(now=True)
                km.cleanup_resources()
            elapsed = time.monotonic() - started
            if elapsed >= limit:
                raise TimeoutError(f"{path.name} exceeded {limit}s whole-notebook limit")
            code_cells = [c for c in nb.cells if c.cell_type == "code" and c.source.strip()]
            if any(c.execution_count is None for c in code_cells):
                raise ValueError(f"Unexecuted code in {path.name}")
            nb.metadata["design_review"] = {"source_sha256": sha256(path),
                                           "elapsed_s": round(elapsed, 3), "status": "passed"}
            executed = destination / path.name
            nbformat.write(nb, executed)
            _notebook_html(nb, path, executed.with_suffix(".html"), source_root.parent)
            title = next((c.source.splitlines()[0].lstrip("# ") for c in nb.cells
                          if c.cell_type == "markdown" and c.source.startswith("# ")), path.stem)
            record = {"name": path.name, "title": title, "status": "passed",
                      "source": path.relative_to(source_root).as_posix(), "source_sha256": sha256(path),
                      "executed_sha256": sha256(executed), "code_cells": len(code_cells),
                      "elapsed_s": round(elapsed, 3), "whole_notebook_limit_s": limit,
                      "html": executed.with_suffix(".html").name, "ipynb": path.name}
            records.append(record)
            progress(f"  Passed in {elapsed:.1f}s; {len(code_cells)} code cells")
    _write_json(destination / "execution_report.json", {"status": "passed", "notebooks": records})
    return records


def render_documents(source: Path, package: Path):
    import mistune

    class Renderer(mistune.HTMLRenderer):
        def heading(self, text, level, **attrs):
            slug = re.sub(r"[^\w\s-]", "", re.sub(r"<[^>]+>", "", html.unescape(text))).lower()
            slug = re.sub(r"\s+", "-", slug.strip())
            return f'<h{level} id="{slug}">{text}</h{level}>\n'

    markdown = mistune.create_markdown(renderer=Renderer(), plugins=["table", "strikethrough", "url"])
    paths = [source / "README.md", *sorted((source / "docs").glob("*.md"))]
    for path in paths:
        body = markdown(path.read_text())
        title = path.stem.replace("_", " ").title()
        home = Path(os.path.relpath(package / "index.html", path.parent)).as_posix()
        page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width, initial-scale=1">'
                f'<title>{html.escape(title)}</title><style>{STYLE}</style></head>'
                f'<body><nav><a href="{home}">← Design review</a>'
                f'<a href="{path.name}" download>Markdown source</a></nav>{body}</body></html>')
        path.with_suffix(".html").write_text(_offline_html(page, path.parent, path.parent, package))


def _write_index(stage: Path, summary: dict, notebooks: list, views: dict, plan: dict, plan_relative: str):
    figures = views["figures"]
    cards = []
    for figure in figures:
        files = figure["files"]
        cards.append(f'<article class="card"><a href="figures/{files["svg"]}">'
                     f'<img src="figures/{files["png"]}" alt="{html.escape(figure["title"])}"></a>'
                     f'<h3>{html.escape(figure["title"])}</h3><p>{html.escape(figure["caption"])}</p>'
                     f'<a href="figures/{files["svg"]}">Full-size annotated SVG</a> · '
                     f'<a href="figures/{files["png"]}">PNG</a></article>')
    rows = "".join(f'<tr><td><a href="notebooks/{n["html"]}">{html.escape(n["title"])}</a></td>'
                   f'<td>Passed · {n["elapsed_s"]:.1f}s</td><td><a href="notebooks/{n["ipynb"]}">.ipynb</a></td></tr>'
                   for n in notebooks)
    selected, balance = summary["selected"], summary["balance"]
    plan_count = len(plan["plates"])
    import yaml
    inputs = yaml.safe_load((stage / "source/platforms/survey_wing/design_point.yaml").read_text())
    target = inputs["requirements"]["endurance_min"]
    findings = [f'{inputs["payload"]["size_for"]} cruise endurance: {selected["endurance_min"]:.2f} min '
                f'against the {target:g} min design target. This is a cruise model, not measured sortie duration.']
    if not balance["target_cg_reachable"]:
        findings.append(f'CG: estimated static margin {balance["static_margin"]:.2%}; the '
                        f'{balance["target_static_margin"]:.0%} target is unreachable in the configured battery bays.')
    checks = summary["propulsion_screening"]["checks"]
    failed = [c["voltage_state"] for c in checks
              if c["candidate"] == checks[0]["candidate"] and not c["thrust_pass"]]
    if failed:
        findings.append('The baseline propeller screening fails the launch thrust target at '
                        + ', '.join(failed) + ' pack voltage; measured thrust/current curves are absent.')
    if not summary["survey_wind"]["tailwind_imaging_compatible"]:
        findings.append('Maximum mission tailwind exceeds the imaging blur bound at modeled cruise airspeed.')
    spacing = 2 * plan["project"]["layout"]["process_clearance_mm"] + plan["project"]["layout"]["part_spacing_mm"]
    findings.append(f'The {plan_count}-bed layout is conservative: convex footprints hide cavity space, '
                    f'exact profiles stay separate, and model spacing is {spacing:g} mm. '
                    'Slicing and material calibration remain open.')
    bullets = "".join(f"<li>{html.escape(v)}</li>" for v in findings)
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Survey wing · Design review dossier</title><style>{STYLE}</style></head><body>
<div class="eyebrow">Wallering Robotics / Independent engineering review</div>
<h1>Survey wing<br>Design, evidence &amp; open questions</h1>
<p class="lead">The complete fixed-wing design in one portable package: actual CAD views, executed Python notebooks, hardware and software interfaces, and the source needed to reproduce the analysis.</p>
<nav><a href="#design">Design dossier</a><a href="#figures">Drawings</a><a href="#notebooks">Notebooks</a><a href="#review">External review</a><a href="{plan_relative}/queue.html">Print beds</a></nav>
<img class="hero" src="source/outputs/review/mechanical/preview_iso.png" alt="Assembled printed survey-wing geometry">
<div class="stats"><div class="stat"><strong>{selected['span_m']:.2f} m</strong>Analytic wingspan</div><div class="stat"><strong>{balance['auw_g']/1000:.2f} kg</strong>Estimated all-up mass</div><div class="stat"><strong>{len(plan['plates'])} beds</strong>{plan['part_count']} printed parts</div><div class="stat"><strong>{len(notebooks)} notebooks</strong>Executed in fresh kernels</div></div>
<p class="note">Engineering review candidate. CAD-derived dimensions and model predictions are evidence about this design; physical assembly, material strength, propulsion, cooling and flight performance remain unverified. Print layouts are unsliced, and physical printing requires explicit user confirmation.</p>
<h2 id="design">Read the design</h2><div class="grid"><article class="card"><h3>Design dossier</h3><p>Requirements, configuration rationale, equations, coordinate frames, interfaces and requirement-by-requirement traceability.</p><a class="button" href="source/docs/design_dossier.html">Open dossier</a></article>
<article class="card"><h3>Independent review brief</h3><p>Reading order, reproducible commands, known issues and a structured findings format for a reviewer or external agent.</p><a class="button" href="source/docs/external_review.html">Open review protocol</a></article>
<article class="card"><h3>Hardware, software &amp; manufacturing</h3><p><a href="source/docs/hardware_spec.html">Dedicated hardware specification</a><br><a href="source/docs/software_spec.html">Mapping software contract</a><br><a href="source/docs/printing.html">Print preparation</a><br><a href="source/outputs/review/index.html">CAD / BOM artifact package</a></p></article></div>
<h2 id="figures">Geometry you can inspect</h2><p>These drawings are generated from the exported CAD. Dashed hardware envelopes are identified separately from modeled printed parts. SVG files combine raster CAD views with vector annotations. Click a drawing for its full-size version.</p><div class="grid">{''.join(cards)}</div>
<h2 id="notebooks">Follow the calculations</h2><p>Each notebook includes its code, inputs, tables, figures, assumptions and review questions. HTML opens offline; the Python notebook remains available for rerunning. No previously saved outputs were reused.</p>
<div class="table-scroll"><table><thead><tr><th>Analysis</th><th>Execution</th><th>Download</th></tr></thead><tbody>{rows}</tbody></table></div>
<p><a href="notebooks/execution_report.json">Execution report</a> · <a href="source/platforms/survey_wing/">Canonical notebook sources</a></p>
<h2 id="review">Questions that matter before committing hardware</h2><ul>{bullets}</ul>
<p>Start an external agent at <a href="source/docs/external_review.md">external_review.md</a> and <a href="review_request.json">review_request.json</a>. The package includes a runnable source snapshot and local evidence; external manufacturer references still require network access.</p>
<pre>cd source
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements-lock.txt -e '.[cad,test,review,printer]'
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLBACKEND=Agg .venv/bin/python -m pytest -q -m 'not cad' --ignore=tests/test_notebooks.py</pre>
<p class="muted"><a href="review_manifest.json">Package provenance and file hashes</a> · <a href="SHA256SUMS">SHA-256 checksums</a> · <a href="figures/views_manifest.json">Drawing geometry provenance</a></p>
</body></html>'''
    (stage / "index.html").write_text(page)


def export_design_review(root: Path, out_dir: Path, *, progress=print) -> dict:
    """Build all evidence before atomically replacing the directory and ZIP."""
    from .printing.project import PrintProject
    from .fab.review_views import export_review_views

    root, out = root.resolve(), out_dir.resolve()
    outputs = root / "outputs"
    if not out.is_relative_to(outputs) or out == outputs:
        raise ValueError("Design review output must be a child of repository outputs/")
    release = outputs / "review"
    parts = outputs / "parts"
    for protected in (release, parts, outputs / "print_projects"):
        if out == protected or out.is_relative_to(protected) or protected.is_relative_to(out):
            raise ValueError("Design review output must be separate from source exports")
    if out.exists() and (not out.is_dir() or (any(out.iterdir()) and not (out / "review_manifest.json").is_file())):
        raise ValueError("Refusing to replace an unrecognized output directory")
    archive = out.with_suffix(".zip")
    if archive == out or (archive.exists() and not archive.is_file()):
        raise ValueError("ZIP destination must be a separate file")
    snapshot = source_snapshot(root)
    source_hashes = _hashes(snapshot)
    release_manifest = validate_release(release, source_hashes)
    project = PrintProject(root)
    plan = project.read_plan()
    if sha256(parts / "manifest.json") != sha256(release / "mechanical/manifest.json"):
        raise ValueError("Mechanical release and print project refer to different CAD exports")
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".design-review-", dir=out.parent))
    temporary = None
    try:
        source = stage / "source"
        for name, data in snapshot.items():
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        progress("Copying validated mechanical, hardware, software and print artifacts")
        shutil.copytree(release, source / "outputs/review")
        # Derive the notebook CAD input from the release's verified exact copy.
        shutil.copytree(release / "mechanical", source / "outputs/parts")
        relative = project.plan_dir().relative_to(root)
        plan_destination = source / relative
        shutil.copytree(project.plan_dir(), plan_destination)
        # Verify the staged evidence rather than trusting a concurrent copy.
        validate_release(source / "outputs/review", source_hashes)
        PrintProject(source).read_plan()
        summary = json.loads((source / "outputs/review/design_summary.json").read_text())
        progress("Rendering dimensioned CAD views and part references")
        views = export_review_views(source / "outputs/parts",
                                    source / "outputs/review/design_summary.json", stage / "figures")
        notebooks = execute_notebooks(source, stage / "notebooks", progress=progress)
        # Markdown sources are preserved beside their browser versions.
        render_documents(source, stage)
        _write_index(stage, summary, notebooks, views, plan,
                     plan_destination.relative_to(stage).as_posix())
        request = {
            "schema_version": "1.0", "platform": "survey_wing", "maturity": "engineering review",
            "start_here": "source/docs/external_review.md",
            "design_dossier": "source/docs/design_dossier.md",
            "notebook_execution": "notebooks/execution_report.json",
            "geometry": "figures/views_manifest.json",
            "findings_schema": "source/docs/review_findings.schema.json",
            "source_root": "source", "print_plan": (relative / "print_plan.json").as_posix(),
            "requested_review": ["requirements and mission feasibility", "aerodynamic and trim assumptions",
                                 "CAD interfaces, assembly and structure", "mass, CG and battery placement",
                                 "propulsion, thermal and power budgets", "camera/software timing contract",
                                 "manufacturability and print-job reduction", "evidence gaps and validation priorities"],
            "physical_print_start_authorized": False,
        }
        request["print_plan"] = "source/" + request["print_plan"]
        _write_json(stage / "review_request.json", request)
        if _hashes(source_snapshot(root)) != source_hashes:
            raise RuntimeError("Source changed while the dossier was building; regenerate")
        validate_release(release, source_hashes)
        project.read_plan()
        try:
            revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
            dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip())
        except (OSError, subprocess.CalledProcessError):
            revision, dirty = "source snapshot (no Git metadata)", None
        manifest = {"schema_version": "1.0", "maturity": "engineering review",
                    "git_revision": revision, "worktree_modified": dirty,
                    "source_sha256": source_hashes,
                    "base_release_git_revision": release_manifest["git_revision"],
                    "notebooks": notebooks, "print_plan_id": project.plan_id(),
                    "execution_python": sys.version.split()[0],
                    "dependencies": {name: importlib.metadata.version(name) for name in
                                     ("nbclient", "nbconvert", "nbformat", "cadquery", "numpy", "matplotlib")},
                    "files": {p.relative_to(stage).as_posix(): {"sha256": sha256(p), "bytes": p.stat().st_size}
                              for p in sorted(stage.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}}
        # Imports into the snapshot create caches; they are neither evidence nor sources.
        for cache in source.rglob("__pycache__"):
            shutil.rmtree(cache)
        _write_json(stage / "review_manifest.json", manifest)
        checksums = {name: entry["sha256"] for name, entry in manifest["files"].items()}
        checksums["review_manifest.json"] = sha256(stage / "review_manifest.json")
        (stage / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())))
        with tempfile.NamedTemporaryFile(prefix=".design-review-", suffix=".zip", dir=out.parent, delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    z.write(path, path.relative_to(stage))
        _publish_pair(stage, out, temporary, archive)
        return {"directory": str(out), "archive": str(archive), "notebooks": len(notebooks),
                "figures": len(views["figures"]), "files": len(manifest["files"])}
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
