"""Review evidence must be portable, current and actually executed."""
import hashlib
import json
from pathlib import Path

import pytest

from uavdesign.design_review import source_snapshot, validate_release, _offline_html


def test_source_snapshot_includes_new_review_code_but_excludes_local_secrets(tmp_path):
    for name, value in {
        "uavdesign/new.py": "pass\n", "docs/review.md": "# Review\n",
        ".local/printing/connection.json": '{"password":"secret"}',
        ".codex/config.toml": "secret = 'test'", ".env": "SECRET=test",
        "outputs/review/old.md": "stale generated output",
        "scripts/__pycache__/fake.py": "cache",
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    assert set(source_snapshot(tmp_path)) == {"uavdesign/new.py", "docs/review.md"}


def test_snapshot_does_not_follow_symlinked_sources(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "target.md").write_text("outside source allowlist")
    (tmp_path / "docs/review.md").symlink_to(tmp_path / "target.md")
    with pytest.raises(ValueError, match="symlink"):
        source_snapshot(tmp_path)


@pytest.fixture
def release(tmp_path):
    (tmp_path / "result.json").write_text('{"value": 42}')
    digest = hashlib.sha256((tmp_path / "result.json").read_bytes()).hexdigest()
    manifest = {"files": {"result.json": {"sha256": digest}},
                "source_sha256": {"uavdesign/model.py": "source-digest"}}
    (tmp_path / "release_manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "SHA256SUMS").write_text(f"{digest}  result.json\n")
    return tmp_path, manifest["source_sha256"]


def test_release_requires_source_and_exact_file_hashes(release):
    root, hashes = release
    validate_release(root, hashes)
    with pytest.raises(ValueError, match="source changed"):
        validate_release(root, {"uavdesign/model.py": "changed"})
    (root / "result.json").write_text('{"value": 99}')
    with pytest.raises(ValueError, match="checksum"):
        validate_release(root, hashes)


def test_release_rejects_unlisted_artifacts(release):
    root, hashes = release
    (root / "stale.png").write_bytes(b"old picture")
    with pytest.raises(ValueError, match="file set"):
        validate_release(root, hashes)


def test_offline_html_has_embedded_output_and_portable_evidence_links(tmp_path):
    pytest.importorskip("nbconvert")
    original = tmp_path / "source/platforms/survey_wing"
    original.mkdir(parents=True)
    docs = tmp_path / "source/docs"
    docs.mkdir(parents=True)
    (docs / "design.md").write_text("# Design")
    requests = tmp_path / "source/integration/feature_requests"
    requests.mkdir(parents=True)
    (requests / "camera.md").write_text("# Camera request")
    document = '''<html><head><script src="https://cdn.invalid/runtime.js"></script>
    <link rel="stylesheet" href="https://cdn.invalid/style.css"></head><body>
    <img src="data:image/png;base64,aGVsbG8=">
    <a href="../../docs/design.md#review">Evidence</a>
    <a href="../../docs/design.md" download>Markdown source</a>
    <a href="../../integration/feature_requests/camera.md">Request</a></body></html>'''
    result = _offline_html(document, original, tmp_path / "notebooks", tmp_path)
    assert "cdn.invalid" not in result
    assert 'href="../source/docs/design.html#review"' in result
    assert "data:image/png;base64,aGVsbG8=" in result
    assert 'href="../source/docs/design.md"' in result
    assert 'href="../source/integration/feature_requests/camera.md"' in result


def test_notebooks_execute_in_fresh_kernels_and_embed_actual_outputs(tmp_path):
    nbformat = pytest.importorskip("nbformat")
    pytest.importorskip("nbconvert")
    from uavdesign.design_review import execute_notebooks

    source = tmp_path / "source"
    folder = source / "platforms/survey_wing"
    folder.mkdir(parents=True)
    for number, code in [(1, "previous = 42\nprint('FRESH_RESULT', previous)"),
                         (2, "assert 'previous' not in globals()\nprint('ISOLATED_KERNEL')")]:
        nb = nbformat.v4.new_notebook(cells=[nbformat.v4.new_markdown_cell(f"# Analysis {number}"),
                                            nbformat.v4.new_code_cell(code)])
        nb.cells[1].outputs = [nbformat.v4.new_output("stream", text="STALE_SAVED_OUTPUT")]
        nbformat.write(nb, folder / f"{number:02d}_analysis.ipynb")
    out = tmp_path / "notebooks"
    records = execute_notebooks(source, out, progress=lambda _: None)
    assert len(records) == 2 and all(r["status"] == "passed" for r in records)
    document = (out / "01_analysis.html").read_text()
    assert "FRESH_RESULT 42" in document
    assert "STALE_SAVED_OUTPUT" not in document
    executed = nbformat.read(out / "02_analysis.ipynb", as_version=4)
    assert executed.cells[1].execution_count == 1
    assert "ISOLATED_KERNEL" in executed.cells[1].outputs[0].text


def test_failed_notebook_has_no_success_report(tmp_path):
    nbformat = pytest.importorskip("nbformat")
    pytest.importorskip("nbconvert")
    from nbclient.exceptions import CellExecutionError
    from uavdesign.design_review import execute_notebooks

    source = tmp_path / "source"
    folder = source / "platforms/survey_wing"
    folder.mkdir(parents=True)
    nbformat.write(nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("raise ValueError('broken analysis')")]),
                   folder / "01_broken.ipynb")
    out = tmp_path / "notebooks"
    with pytest.raises(CellExecutionError, match="broken analysis"):
        execute_notebooks(source, out, progress=lambda _: None)
    assert not (out / "execution_report.json").exists()
    assert not (out / "01_broken.html").exists()
