"""Execute every platform notebook top-to-bottom on a fresh kernel.

Enforces the repo convention that notebooks must run clean. Skipped when the
notebook tooling is not installed; run with `pytest -m notebooks`.
"""

from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")
nbclient = pytest.importorskip("nbclient")

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOKS = sorted((ROOT / "platforms").glob("*/*.ipynb"))


@pytest.mark.notebooks
@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_notebook_runs(path, monkeypatch):
    monkeypatch.setenv("MPLBACKEND", "Agg")
    nb = nbformat.read(path, as_version=4)
    client = nbclient.NotebookClient(
        nb, timeout=180, kernel_name="python3", resources={"metadata": {"path": str(path.parent)}}
    )
    client.execute()
