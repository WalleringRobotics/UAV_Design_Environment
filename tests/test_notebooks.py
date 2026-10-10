"""Execute every platform notebook top-to-bottom on a fresh kernel.

Enforces the repo convention that notebooks must run clean. Skipped when the
notebook tooling is not installed; run with `pytest -m notebooks`.
"""

import json
from pathlib import Path
import time

import pytest

nbformat = pytest.importorskip("nbformat")
nbclient = pytest.importorskip("nbclient")

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOKS = sorted((ROOT / "platforms").glob("*/*.ipynb"))


@pytest.mark.notebooks
@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_notebook_runs(path, monkeypatch):
    monkeypatch.setenv("MPLBACKEND", "Agg")
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        monkeypatch.setenv(key, "1")
    limited = path.parent.name == "survey_wing" and not path.name.startswith("07_")
    started = time.monotonic()

    def check_deadline(**_):
        if limited and time.monotonic() - started >= 60:
            raise TimeoutError(f"{path.name} exceeded the whole-notebook 60-second limit")

    nb = nbformat.read(path, as_version=4)
    client = nbclient.NotebookClient(
        nb, timeout=180, kernel_name="python3", on_cell_start=check_deadline,
        resources={"metadata": {"path": str(path.parent)}}
    )
    status = "failed"
    try:
        client.execute()
        elapsed = time.monotonic() - started
        if limited:
            assert elapsed < 60, f"{path.name}: {elapsed:.2f}s exceeds whole-notebook limit"
        status = "passed"
    finally:
        timing_path = ROOT / "outputs/validation/notebook_timings.json"
        timing_path.parent.mkdir(parents=True, exist_ok=True)
        timings = json.loads(timing_path.read_text()) if timing_path.exists() else {}
        timings[str(path.relative_to(ROOT))] = {
            "elapsed_s": round(time.monotonic() - started, 3), "status": status,
            "whole_notebook_limit_s": 60 if limited else None,
        }
        timing_path.write_text(json.dumps(timings, indent=2, sort_keys=True) + "\n")


@pytest.mark.notebooks
def test_survey_wing_fabrication_without_manifest(tmp_path, monkeypatch):
    """A fresh checkout explains the build step without fabricating CAD results."""
    for key, value in (("MPLBACKEND", "Agg"), ("OPENBLAS_NUM_THREADS", "1"),
                       ("OMP_NUM_THREADS", "1"), ("MKL_NUM_THREADS", "1")):
        monkeypatch.setenv(key, value)
    path = ROOT / "platforms/survey_wing/07_fabrication.ipynb"
    nb = nbformat.read(path, as_version=4)
    original = 'manifest_path=REPO_ROOT/"outputs/parts/manifest.json"'
    replacement = f"manifest_path=Path({str(tmp_path / 'absent-manifest.json')!r})"
    changed = 0
    for cell in nb.cells:
        if cell.cell_type == "code" and original in cell.source:
            cell.source = cell.source.replace(original, replacement)
            changed += 1
    assert changed == 1
    nbclient.NotebookClient(nb, timeout=180, kernel_name="python3",
                           resources={"metadata": {"path": str(path.parent)}}).execute()
    text = "".join(output.get("text", "") for cell in nb.cells
                   for output in cell.get("outputs", []) if output.get("output_type") == "stream")
    assert "No parts manifest. Run: python scripts/build_parts.py" in text
