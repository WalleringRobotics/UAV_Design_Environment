from pathlib import Path
import pytest
from uavdesign import design as D
from uavdesign.artifacts import bom_rows


@pytest.fixture(scope="module")
def design():
    return D.run(solve_stability=False)


def test_bom_contains_complete_nonprinted_inventory_once(design):
    for config, payload in design.payloads.items():
        rows = bom_rows(design, config)
        names = [r["item"] for r in rows]
        assert len(names) == len(set(names))
        assert names.count("payload:compute") == 1
        mass = sum(r["total_mass_g"] for r in rows)
        expected = (design.electronics.avionics_mass_g
                    + sum(design.electronics.propulsion_masses_g.values())
                    + payload.mass_g - payload.cage_structure_mass_g
                    + design.electronics.pack.mass_g)
        assert mass == pytest.approx(expected)
        assert all(r["cost_status"] == "quote required" for r in rows)


def test_camera_sizing_matches_hardware_candidate(design):
    camera = design.design["survey"]["camera"]
    spec = design.payloads["orin"].cage_members["camera"]
    assert "a2A5320-7gcPRO" in spec["part"]
    assert (camera["pixels_across"], camera["pixels_along"]) == (5320, 3032)
    assert spec["envelope_mm"] == [29, 29, 55.5]


@pytest.fixture
def cad_export(tmp_path, monkeypatch):
    """Tiny on-disk export, with CAD imports replaced by its validation seam.

    File validation has no dependency on OpenCascade or a minutes-long build.
    The separate CAD suite checks that real solids and exports are valid.
    """
    import hashlib
    import json
    import sys
    from types import ModuleType, SimpleNamespace

    fake_build = ModuleType("uavdesign.fab.build")
    fake_build.result_signature = lambda result: result.signature
    fake_build.verify_design_snapshot = lambda design: None
    monkeypatch.setitem(sys.modules, "uavdesign.fab.build", fake_build)
    names = ("wing_L", "wing_R")
    result = SimpleNamespace(signature="current-design", design=SimpleNamespace(),
                             parts=[SimpleNamespace(name=name) for name in names])
    for ext in ("stl", "step"):
        (tmp_path / ext).mkdir()
        for name in names:
            (tmp_path / ext / f"{name}.{ext}").write_text(f"fixture {name} {ext}\n")
    (tmp_path / "assembly.step").write_text("fixture assembly\n")
    (tmp_path / "PRINT_LIST.md").write_text("fixture print list\n")
    manifest = {"result_signature": result.signature,
                "file_sha256": {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in tmp_path.rglob("*") if p.is_file() and p.suffix in (".stl", ".step")}}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return result, tmp_path, manifest, fake_build


def test_matching_cad_export_validates_without_cad(cad_export):
    from uavdesign.artifacts import validate_cad_export
    result, parts, _, _ = cad_export
    validate_cad_export(result, parts)


def test_stale_cad_result_is_rejected(cad_export):
    from uavdesign.artifacts import validate_cad_export
    result, parts, _, _ = cad_export
    result.signature = "changed-design"
    with pytest.raises(ValueError, match="stale"):
        validate_cad_export(result, parts)


@pytest.mark.parametrize("checksum_state", ["missing", "empty", "partial"])
def test_checksum_manifest_is_required_and_complete(cad_export, checksum_state):
    import json
    from uavdesign.artifacts import validate_cad_export
    result, parts, manifest, _ = cad_export
    if checksum_state == "missing":
        manifest.pop("file_sha256")
    elif checksum_state == "empty":
        manifest["file_sha256"] = {}
    else:
        manifest["file_sha256"].pop("stl/wing_L.stl")
    (parts / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="(?i)checksum|hash"):
        validate_cad_export(result, parts)


@pytest.mark.parametrize("ext", ["stl", "step"])
@pytest.mark.parametrize("change", ["missing", "extra", "tampered"])
def test_mechanical_file_mutations_are_rejected(cad_export, ext, change):
    from uavdesign.artifacts import validate_cad_export
    result, parts, _, _ = cad_export
    target = parts / ext / f"wing_L.{ext}"
    if change == "missing":
        target.unlink()
    elif change == "extra":
        (parts / ext / f"obsolete_part.{ext}").write_text("stale part\n")
    else:
        target.write_text("changed after export\n")
    with pytest.raises(ValueError, match="(?i)file set|checksum"):
        validate_cad_export(result, parts)


@pytest.mark.parametrize("relative", [
    "stl/obsolete/old_part.stl", "step/obsolete/old_part.step",
    "stl/old_part.STL", "step/old_part.STEP",
])
def test_nested_or_uppercase_unexpected_cad_files_are_rejected(cad_export, relative):
    from uavdesign.artifacts import validate_cad_export
    result, parts, _, _ = cad_export
    unexpected = parts / relative
    unexpected.parent.mkdir(parents=True, exist_ok=True)
    unexpected.write_text("unmanifested obsolete geometry\n")
    with pytest.raises(ValueError, match="(?i)file set|checksum|artifact set"):
        validate_cad_export(result, parts)


def test_missing_assembly_is_rejected(cad_export):
    from uavdesign.artifacts import validate_cad_export
    result, parts, _, _ = cad_export
    (parts / "assembly.step").unlink()
    with pytest.raises(ValueError, match="(?i)checksum|hash|missing"):
        validate_cad_export(result, parts)


def test_changed_build_inputs_are_rejected_before_packaging(cad_export):
    from uavdesign.artifacts import validate_cad_export
    result, parts, _, fake_build = cad_export

    def changed(design):
        raise RuntimeError("Design inputs or implementation changed during build")

    fake_build.verify_design_snapshot = changed
    with pytest.raises(RuntimeError, match="changed during build"):
        validate_cad_export(result, parts)


@pytest.fixture
def release_pair(tmp_path):
    """Old published pair and independently completed replacements."""
    out, stage = tmp_path / "review", tmp_path / ".review-stage"
    archive, temporary = tmp_path / "review.zip", tmp_path / ".review-new.zip"
    out.mkdir()
    stage.mkdir()
    (out / "version.txt").write_text("old directory")
    (stage / "version.txt").write_text("new directory")
    archive.write_bytes(b"old archive")
    temporary.write_bytes(b"new archive")
    return stage, out, temporary, archive


def _assert_old_pair_restored(out, archive):
    assert (out / "version.txt").read_text() == "old directory"
    assert archive.read_bytes() == b"old archive"
    assert not out.with_name(f".{out.name}-previous").exists()
    assert not archive.with_suffix(".zip.previous").exists()


def test_release_pair_rolls_back_failure_on_second_backup_rename(release_pair, monkeypatch):
    from uavdesign.artifacts import _publish_pair
    stage, out, temporary, archive = release_pair
    real_rename = Path.rename

    def fail_archive_backup(self, target):
        if self == archive:
            raise OSError("injected archive backup failure")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_archive_backup)
    with pytest.raises(OSError, match="injected archive backup failure"):
        _publish_pair(stage, out, temporary, archive)
    _assert_old_pair_restored(out, archive)
    assert (stage / "version.txt").read_text() == "new directory"
    assert temporary.read_bytes() == b"new archive"


def test_release_pair_rolls_back_failure_publishing_directory(release_pair, monkeypatch):
    from uavdesign.artifacts import _publish_pair
    stage, out, temporary, archive = release_pair
    real_rename = Path.rename

    def fail_stage_publish(self, target):
        if self == stage:
            raise OSError("injected stage publication failure")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_stage_publish)
    with pytest.raises(OSError, match="injected stage publication failure"):
        _publish_pair(stage, out, temporary, archive)
    _assert_old_pair_restored(out, archive)


def test_release_pair_rolls_back_failed_zip_replacement(release_pair, monkeypatch):
    from uavdesign.artifacts import _publish_pair
    stage, out, temporary, archive = release_pair
    real_replace = Path.replace

    def fail_zip_publish(self, target):
        if self == temporary:
            raise OSError("injected ZIP publication failure")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_zip_publish)
    with pytest.raises(OSError, match="injected ZIP publication failure"):
        _publish_pair(stage, out, temporary, archive)
    _assert_old_pair_restored(out, archive)
    assert temporary.read_bytes() == b"new archive"


def test_release_pair_success_replaces_both_and_removes_backups(release_pair):
    from uavdesign.artifacts import _publish_pair
    stage, out, temporary, archive = release_pair
    _publish_pair(stage, out, temporary, archive)
    assert (out / "version.txt").read_text() == "new directory"
    assert archive.read_bytes() == b"new archive"
    assert not stage.exists()
    assert not temporary.exists()
    assert not out.with_name(f".{out.name}-previous").exists()
    assert not archive.with_suffix(".zip.previous").exists()


@pytest.mark.parametrize("collision", ["review", "cad", "directory_archive"])
def test_review_archive_cannot_alias_data_directories(tmp_path, collision):
    from types import SimpleNamespace
    from uavdesign.artifacts import export_review
    out, parts = tmp_path / "review", tmp_path / "parts"
    if collision == "review":
        out = tmp_path / "review.zip"
    elif collision == "cad":
        parts = tmp_path / "review.zip"
    else:
        (tmp_path / "review.zip").mkdir()
    parts.mkdir()
    marker = parts / "precious-existing-model.step"
    marker.write_text("must remain intact")
    with pytest.raises(ValueError, match="ZIP"):
        export_review(SimpleNamespace(design=SimpleNamespace()), out, parts)
    assert marker.read_text() == "must remain intact"


@pytest.mark.cad
def test_cad_manifest_compares_balance_with_exported_payload_evaluation(tmp_path, monkeypatch):
    """CM5 shares the Orin-sized airframe but has its own evaluated mass."""
    import json
    from types import SimpleNamespace as NS

    pytest.importorskip("cadquery")
    from uavdesign.fab import build as B

    part = NS(name="fixture", part=NS(solid=object(), notes=[]), profile={})
    design = NS(calibration={}, selected=NS(auw_kg=3.4),
                evaluations={"orin": NS(auw_kg=3.4), "cm5": NS(auw_kg=3.2)})
    result = NS(design=design, payload_config="cm5", parts=[part], printed_mass_g={},
                fab={"printer": {"name": "test", "bed_x_mm": 250, "bed_y_mm": 220, "max_z_mm": 270}},
                balance=NS(auw_g=3205, summary=lambda: {"auw_g": 3205}),
                part_table=lambda: [{"part": "fixture"}])
    monkeypatch.setattr(B, "result_signature", lambda result: "fixture-signature")
    monkeypatch.setattr(B.D, "airframe_geometry", lambda design: {})
    monkeypatch.setattr(B, "print_oriented", lambda part, printer: object())
    monkeypatch.setattr(B.cq.Compound, "makeCompound", lambda shapes: object())
    monkeypatch.setattr(B.cq.exporters, "export", lambda shape, path, **kwargs: Path(path).write_text("fixture geometry\n"))
    monkeypatch.setattr(B, "print_list_markdown", lambda result: "fixture print list\n")

    B._export_files(result, tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["payload_config"] == "cm5"
    assert manifest["sizing_auw_g"] == pytest.approx(3200)
    assert manifest["sizing_balance_error_fraction"] == pytest.approx(abs(3205 / 3200 - 1))
