"""Validate actual CLI exports, independently of CadQuery's BREP validity checks.

A connected valid CAD solid does not by itself prove that its STL tessellation
is closed. These tests inspect binary STL bytes and welded triangle edges.
They use only standard-library/NumPy code, but carry the ``cad`` marker because
CI must run the parts CLI first. A checkout without exports skips explicitly.
"""

import hashlib
import json
from pathlib import Path
import struct

import numpy as np
import pytest

pytestmark = pytest.mark.cad
ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "outputs/parts"
# 0.1 micrometre is below print resolution and the 0.05 mm export deflection.
# Welding only removes numerical disagreement in coincident face vertices.
WELD_MM = 1e-4


@pytest.fixture(scope="module")
def exported():
    path = PARTS / "manifest.json"
    if not path.is_file():
        pytest.skip("No exported parts manifest: run python scripts/build_parts.py before CAD artifact tests")
    manifest = json.loads(path.read_text())
    assert manifest.get("parts"), "Export manifest has no parts"
    return manifest


def _binary_stl_triangles(path):
    data = path.read_bytes()
    assert len(data) >= 84, f"{path.name}: incomplete binary STL header"
    count = struct.unpack_from("<I", data, 80)[0]
    assert count > 0, f"{path.name}: STL has no triangles"
    assert len(data) == 84 + 50 * count, f"{path.name}: STL triangle count/byte length disagree"
    dtype = np.dtype([("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")])
    records = np.frombuffer(data, dtype=dtype, count=count, offset=84)
    assert np.all(np.isfinite(records["vertices"])), f"{path.name}: nonfinite triangle coordinates"
    assert np.all(np.isfinite(records["normal"])), f"{path.name}: nonfinite facet normals"
    return records["vertices"].astype(np.float64)


def _welded_edge_counts(triangles, weld_mm=WELD_MM):
    """Counts for unordered mesh edges after sub-print-resolution vertex welding.

    This tests edge closure/manifold incidence. It does not certify absence of
    self-intersections, correct shell nesting, strength, or connected BREP solids.
    Faces collapsed by the numerical weld are counted and excluded from edges.
    """
    coordinates = np.asarray(triangles, dtype=float).reshape(-1, 3)
    quantized = np.rint(coordinates / weld_mm).astype(np.int64)
    _, inverse = np.unique(quantized, axis=0, return_inverse=True)
    faces = inverse.reshape(-1, 3)
    keep = ((faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 2] != faces[:, 0]))
    collapsed = int(np.count_nonzero(~keep))
    faces = faces[keep]
    if not len(faces):
        return np.array([], dtype=int), collapsed
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    edges.sort(axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return counts, collapsed


def test_manifest_matches_exact_step_stl_and_assembly_files(exported):
    names = [part["part"] for part in exported["parts"]]
    assert len(names) == len(set(names)), "Repeated part identifiers in export manifest"
    expected = {"assembly.step"}
    for row in exported["parts"]:
        for extension in ("step", "stl"):
            relative = f"{extension}/{row['part']}.{extension}"
            assert row["files"][extension] == relative
            expected.add(relative)
    actual = {str(path.relative_to(PARTS)) for path in PARTS.rglob("*")
              if path.is_file() and path.suffix.lower() in (".stl", ".step")}
    assert actual == expected, f"Missing={expected - actual}, unexpected={actual - expected}"
    assert set(exported["file_sha256"]) == expected, "Manifest hash list is incomplete or stale"
    for relative in sorted(expected):
        path = (PARTS / relative).resolve()
        assert path.is_relative_to(PARTS.resolve()), f"Artifact escapes output directory: {relative}"
        assert path.is_file() and path.stat().st_size > 0, relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == exported["file_sha256"][relative], relative


def test_exported_stls_have_finite_binary_triangles(exported):
    for row in exported["parts"]:
        triangles = _binary_stl_triangles(PARTS / row["files"]["stl"])
        assert triangles.shape[0] > 0, row["part"]


def test_exported_stl_mesh_edges_are_watertight(exported):
    failures = []
    for row in exported["parts"]:
        triangles = _binary_stl_triangles(PARTS / row["files"]["stl"])
        counts, collapsed = _welded_edge_counts(triangles)
        if not len(counts) or np.any(counts != 2):
            failures.append({"part": row["part"], "boundary_edges": int(np.count_nonzero(counts == 1)),
                             "nonmanifold_edges": int(np.count_nonzero(counts > 2)),
                             "collapsed_faces_at_weld_tolerance": collapsed})
    assert not failures, f"STL edge closure failed at {WELD_MM} mm weld tolerance: {failures}"


def test_exported_stls_are_print_oriented_within_declared_bed(exported):
    printer = exported["printer"]
    # Tessellation can be within the exported deflection of the BREP extremum.
    tolerance_mm = 0.1
    margin = printer.get("margin_mm", 5)
    for row in exported["parts"]:
        vertices = _binary_stl_triangles(PARTS / row["files"]["stl"]).reshape(-1, 3)
        lower, upper = vertices.min(axis=0), vertices.max(axis=0)
        assert np.all(lower[:2] >= margin - tolerance_mm), (row["part"], lower)
        assert upper[0] <= printer["bed_x_mm"] - margin + tolerance_mm, (row["part"], upper)
        assert upper[1] <= printer["bed_y_mm"] - margin + tolerance_mm, (row["part"], upper)
        assert abs(lower[2]) <= tolerance_mm, (row["part"], lower)
        assert upper[2] <= printer["max_z_mm"] + tolerance_mm, (row["part"], upper)


def test_mesh_checker_distinguishes_closed_and_missing_facet():
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
    tetrahedron = vertices[[[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]]]
    counts, collapsed = _welded_edge_counts(tetrahedron)
    assert collapsed == 0 and np.all(counts == 2)
    open_counts, _ = _welded_edge_counts(tetrahedron[:-1])
    assert np.count_nonzero(open_counts == 1) == 3


def test_binary_stl_parser_rejects_truncation_and_nonfinite_vertices(tmp_path):
    path = tmp_path / "triangle.stl"
    header = bytes(80) + struct.pack("<I", 1)
    record = struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0)
    path.write_bytes(header + record)
    assert _binary_stl_triangles(path).shape == (1, 3, 3)
    path.write_bytes(header + record[:-1])
    with pytest.raises(AssertionError, match="byte length"):
        _binary_stl_triangles(path)
    record = struct.pack("<12fH", 0, 0, 1, float("nan"), 0, 0, 1, 0, 0, 0, 1, 0, 0)
    path.write_bytes(header + record)
    with pytest.raises(AssertionError, match="nonfinite triangle"):
        _binary_stl_triangles(path)
