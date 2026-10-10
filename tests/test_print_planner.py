"""Plate geometry, provenance, isolation and publication checks without CAD."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import zipfile
from xml.etree import ElementTree as ET

import numpy as np
import pytest

from uavdesign.printing import planner


PROJECT = {"schema_version": "1.0", "name": "test_core_one",
           "printer": {"name": "Prusa CORE One+", "bed_mm": [250, 220, 270], "nozzle_diameter_mm": 0.4},
           "layout": {"bed_margin_mm": 5, "part_spacing_mm": 5, "process_clearance_mm": 8, "single_part_above_height_mm": 150}}


def _stl(size=(20, 15, 10), offset=(100, 100, 0)):
    vertices = np.array([[x, y, z] for x in (0, size[0]) for y in (0, size[1]) for z in (0, size[2])], dtype=float) + offset
    faces = [[0, 2, 3], [0, 3, 1], [4, 5, 7], [4, 7, 6], [0, 1, 5], [0, 5, 4],
             [2, 6, 7], [2, 7, 3], [0, 4, 6], [0, 6, 2], [1, 3, 7], [1, 7, 5]]
    return bytes(80) + struct.pack("<I", len(faces)) + b"".join(struct.pack("<12fH", 0, 0, 1, *vertices[face].ravel(), 0) for face in faces)


def _inventory(tmp_path, specs):
    root = tmp_path / "source"
    (root / "stl").mkdir(parents=True)
    manifest = {"schema_version": "1.0", "units": {"geometry": "mm"}, "result_signature": "fixture", "parts": [], "file_sha256": {}}
    for i, spec in enumerate(specs):
        name = f"part_{i}"
        rel = f"stl/{name}.stl"
        raw = _stl(spec.get("size", (20, 15, 10)))
        (root / rel).write_bytes(raw)
        settings = {"material": "asa", "layer_height_mm": 0.2, "perimeters": 3, **spec.get("settings", {})}
        manifest["parts"].append({"part": name, "profile": spec.get("profile", "shell"), "material": "ASA", "mass_g": 10,
                                  "settings": settings, "files": {"stl": rel}})
        manifest["file_sha256"][rel] = hashlib.sha256(raw).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root


def _rewrite_manifest(root, mutate):
    path = root / "manifest.json"
    manifest = json.loads(path.read_text())
    mutate(manifest)
    path.write_text(json.dumps(manifest))


def _assert_clearances(plan):
    project = plan["project"]
    bed = project["printer"]["bed_mm"]
    margin = project["layout"]["bed_margin_mm"]
    gap = project["layout"]["part_spacing_mm"]
    halo = project["layout"]["process_clearance_mm"]
    for plate in plan["plates"]:
        placements = plate["placements"]
        for p in placements:
            low, high = np.array(p["reserved_bounds_mm"]["min"]), np.array(p["reserved_bounds_mm"]["max"])
            assert np.all(low >= margin - 1e-6)
            assert np.all(high <= np.array(bed[:2]) - margin + 1e-6)
            actual = p["placed_bounds_mm"]
            np.testing.assert_allclose(np.array(actual["min"][:2]) - low, halo, atol=1e-6)
            np.testing.assert_allclose(high - np.array(actual["max"][:2]), halo, atol=1e-6)
            assert actual["min"][2] == 0
            assert actual["max"][2] <= bed[2]
        for i, a in enumerate(placements):
            for b in placements[i + 1:]:
                assert planner._polygon_distance(a["placed_polygon_mm"], b["placed_polygon_mm"]) >= 2 * halo + gap - 1e-6
                assert planner._polygon_distance(a["reserved_polygon_mm"], b["reserved_polygon_mm"]) >= gap - 1e-6


def test_plan_is_deterministic_isolates_settings_and_covers_every_part(tmp_path):
    source = _inventory(tmp_path, [{}, {}, {"settings": {"layer_height_mm": 0.25}}, {"profile": "structural"}, {"size": (20, 15, 200)}, {}])
    plan = planner.export_plan(source, PROJECT, tmp_path / "first")
    second = planner.export_plan(source, PROJECT, tmp_path / "second")
    assert plan == second
    assert plan["artifact_state"] == "arranged_geometry" and plan["sliced"] is False
    names = [p["part"] for plate in plan["plates"] for p in plate["placements"]]
    assert sorted(names) == [f"part_{i}" for i in range(6)]
    assert len(plan["plates"]) == 4
    for plate in plan["plates"]:
        assert all(p["profile"] == plate["profile"] and p["settings"] == plate["settings"] for p in plate["placements"])
        if any(p["size_mm"][2] > 150 for p in plate["placements"]):
            assert len(plate["placements"]) == 1
    _assert_clearances(plan)
    assert plan["manifest_sha256"] == hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
    for relative, digest in plan["file_sha256"].items():
        assert hashlib.sha256((tmp_path / "first" / relative).read_bytes()).hexdigest() == digest


def test_3mf_has_mm_units_named_objects_and_baked_verified_placements(tmp_path):
    source = _inventory(tmp_path, [{}, {}])
    plan = planner.export_plan(source, PROJECT, tmp_path / "plan")
    plate = plan["plates"][0]
    with zipfile.ZipFile(tmp_path / "plan" / plate["files"]["3mf"]) as archive:
        assert archive.testzip() is None
        assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} == set(archive.namelist())
        model = ET.fromstring(archive.read("3D/3dmodel.model"))
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    assert model.attrib["unit"] == "millimeter"
    objects = model.findall("m:resources/m:object", ns)
    assert [obj.attrib["name"] for obj in objects] == [p["part"] for p in plate["placements"]]
    for obj, placement in zip(objects, plate["placements"]):
        vertices = np.array([[float(v.attrib[k]) for k in ("x", "y", "z")] for v in obj.findall("m:mesh/m:vertices/m:vertex", ns)])
        np.testing.assert_allclose(vertices.min(axis=0), placement["placed_bounds_mm"]["min"])
        np.testing.assert_allclose(vertices.max(axis=0), placement["placed_bounds_mm"]["max"])
        assert len(obj.findall("m:mesh/m:triangles/m:triangle", ns)) == 12
    assert len(model.findall("m:build/m:item", ns)) == 2


def test_z_rotation_preserves_mesh_height_and_fits_narrow_bed(tmp_path):
    source = _inventory(tmp_path, [{"size": (70, 25, 30)}])
    project = copy.deepcopy(PROJECT)
    project["printer"]["bed_mm"] = [60, 120, 100]
    plan = planner.export_plan(source, project, tmp_path / "plan")
    p = plan["plates"][0]["placements"][0]
    assert p["rotation_z_deg"] == 90
    np.testing.assert_allclose(np.array(p["placed_bounds_mm"]["max"]) - p["placed_bounds_mm"]["min"], [25, 70, 30])
    _assert_clearances(plan)


@pytest.mark.parametrize("change", ["tamper", "missing_hash", "extra_file", "duplicate", "traversal", "absolute", "symlink"])
def test_rejects_ambiguous_or_untrusted_inventory(tmp_path, change):
    source = _inventory(tmp_path, [{}])
    if change == "tamper":
        (source / "stl/part_0.stl").write_bytes(b"tampered")
    elif change == "missing_hash":
        _rewrite_manifest(source, lambda m: m["file_sha256"].clear())
    elif change == "extra_file":
        (source / "stl/extra.stl").write_bytes(_stl())
    elif change == "duplicate":
        _rewrite_manifest(source, lambda m: m["parts"].append(m["parts"][0]))
    else:
        outside = tmp_path / "outside.stl"
        outside.write_bytes(_stl())
        if change == "symlink":
            (source / "stl/part_0.stl").unlink()
            (source / "stl/part_0.stl").symlink_to(outside)
        else:
            _rewrite_manifest(source, lambda m: m["parts"][0]["files"].update(stl="../outside.stl" if change == "traversal" else str(outside)))
    with pytest.raises(ValueError):
        planner.load_inventory(source)


@pytest.mark.parametrize("invalid", ["nonfinite", "truncated", "raised", "flat"])
def test_rejects_invalid_mesh_even_with_matching_checksum(tmp_path, invalid):
    source = _inventory(tmp_path, [{}])
    raw = {"nonfinite": _stl(offset=(float("nan"), 0, 0)), "truncated": _stl()[:-1],
           "raised": _stl(offset=(100, 100, 2)), "flat": _stl(size=(20, 15, 0))}[invalid]
    (source / "stl/part_0.stl").write_bytes(raw)
    _rewrite_manifest(source, lambda m: m["file_sha256"].update({"stl/part_0.stl": hashlib.sha256(raw).hexdigest()}))
    with pytest.raises(ValueError):
        planner.load_inventory(source)


def test_clearance_and_height_are_enforced_not_just_mesh_fit(tmp_path):
    source = _inventory(tmp_path, [{"size": (239, 209, 10)}])
    with pytest.raises(ValueError, match="process clearance"):
        planner.export_plan(source, PROJECT, tmp_path / "plan")
    project = copy.deepcopy(PROJECT)
    project["layout"]["process_clearance_mm"] = 0
    project["printer"]["bed_mm"][2] = 9
    with pytest.raises(ValueError, match="height"):
        planner.export_plan(source, project, tmp_path / "plan")


def test_output_aliases_and_unknown_directories_are_preserved(tmp_path):
    source = _inventory(tmp_path, [{}])
    for target in (source, source / "nested", source.parent):
        with pytest.raises(ValueError, match="separate"):
            planner.export_plan(source, PROJECT, target)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "precious.txt").write_text("keep")
    with pytest.raises(ValueError, match="unrecognized"):
        planner.export_plan(source, PROJECT, unrelated)
    assert (unrelated / "precious.txt").read_text() == "keep"


def test_failed_replacement_restores_previous_plan(tmp_path, monkeypatch):
    source = _inventory(tmp_path, [{}])
    out = tmp_path / "plan"
    original = planner.export_plan(source, PROJECT, out)
    real_rename = Path.rename

    def fail_stage(path, target):
        if path.name.startswith(".plan-") and path.name != ".plan-previous":
            raise OSError("injected publish failure")
        return real_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_stage)
    with pytest.raises(OSError, match="injected"):
        planner.export_plan(source, PROJECT, out)
    assert json.loads((out / "print_plan.json").read_text()) == original
    assert not (tmp_path / ".plan-previous").exists()


def test_source_change_during_export_does_not_publish(tmp_path, monkeypatch):
    source = _inventory(tmp_path, [{}])
    real_write = planner.write_plate

    def mutate(*args, **kwargs):
        real_write(*args, **kwargs)
        (source / "stl/part_0.stl").write_bytes(_stl(size=(21, 15, 10)))

    monkeypatch.setattr(planner, "write_plate", mutate)
    with pytest.raises(ValueError, match="checksum"):
        planner.export_plan(source, PROJECT, tmp_path / "plan")
    assert not (tmp_path / "plan").exists()


def test_current_real_airframe_inventory_is_covered_with_clearance():
    root = Path(__file__).resolve().parents[1] / "outputs/parts"
    if not (root / "manifest.json").is_file():
        pytest.skip("CAD artifacts are absent; generate them to check actual airframe plates")
    inventory = planner.load_inventory(root)
    project = copy.deepcopy(PROJECT)
    project["layout"]["single_part_above_height_mm"] = None
    plates = planner._arrange(inventory, project)
    plan = {"project": project, "plates": plates}
    _assert_clearances(plan)
    assert sorted(p["part"] for plate in plates for p in plate["placements"]) == sorted(p["part"] for p in inventory["parts"])
    assert all(p["triangle_count"] > 0 for p in inventory["parts"])
    assert len(plates) <= 21, "Regressed to sparse bed layouts instead of polygon nesting"
    assert sum(p["profile"] == "elevon" for p in plates) == 1
    assert sum(p["profile"] == "skid" for p in plates) == 1


def test_default_allows_tall_parts_together_but_explicit_threshold_is_respected(tmp_path):
    source = _inventory(tmp_path, [{"size": (20, 15, 200)}, {"size": (20, 15, 200)}])
    project = copy.deepcopy(PROJECT)
    del project["layout"]["single_part_above_height_mm"]
    plan = planner.export_plan(source, project, tmp_path / "shared")
    assert plan["project"]["layout"]["single_part_above_height_mm"] is None
    assert len(plan["plates"]) == 1
    isolated = planner.export_plan(source, PROJECT, tmp_path / "isolated")
    assert len(isolated["plates"]) == 2


def test_polygon_distance_and_round_clearance_reject_near_misses():
    a = np.array([[0., 0.], [100, 0], [100, 10], [0, 10]])
    b = a + [0, 31]
    assert planner._polygon_distance(a, b) == pytest.approx(21)
    assert planner._polygon_distance(a, a + [0, 9]) == 0
    assert planner._polygon_distance(a, a + [103, 14]) == pytest.approx(5)
    buffered = planner._buffer(a, 8)
    np.testing.assert_allclose(buffered.min(axis=0), [-8, -8], atol=1e-8)
    np.testing.assert_allclose(buffered.max(axis=0), [108, 18], atol=1e-8)
    assert planner._polygon_distance(buffered, planner._buffer(b, 8)) == pytest.approx(5)


def test_layout_validator_rejects_overlap_and_geometry_changes(tmp_path):
    source = _inventory(tmp_path, [{}, {}])
    plan = planner.export_plan(source, PROJECT, tmp_path / "plan")
    inventory = planner.load_inventory(source)
    broken = copy.deepcopy(plan["plates"])
    broken[0]["placements"][1]["translation_mm"][0] += 2
    with pytest.raises(ValueError, match="transform"):
        planner._validate_layout(broken, inventory, plan["project"])
    broken = copy.deepcopy(plan["plates"])
    second = broken[0]["placements"][1]
    first = broken[0]["placements"][0]
    for key in ("translation_mm", "placed_polygon_mm"):
        second[key] = first[key]
    with pytest.raises(ValueError, match="clearance"):
        planner._validate_layout(broken, inventory, plan["project"])
