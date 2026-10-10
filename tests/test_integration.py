"""Boundary tests for exported design inputs, budgets and coordinate conventions."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from uavdesign.integration import (
    ROOT, build_handoff, cad_point_to_flu_m, camera_profile, export_integration,
    resource_budget, validate_handoff,
)


def test_handoff_derives_hardware_and_preserves_unqualified_state():
    data = build_handoff()
    result = validate_handoff(data)
    assert result["schema_valid"] and not result["survey_ready"]
    assert data["hardware"]["camera"]["selection_policy"]["substitute_allowed"]
    assert set(data["hardware"]["compute_variants"]) == {"orin", "cm5"}
    assert data["navigation"]["flight_gnss_independent"]
    assert data["geometry"]["gsd_m_per_px"] == pytest.approx(0.01096)
    assert data["geometry"]["forward_motion_blur_px"] == pytest.approx(0.6)
    assert data["mission"]["survey_duration_s"] == 3000
    assert data["resources"]["storage_capacity_pass"] is None


def test_full_depth_camera_data_exceeds_gige_budget():
    data = build_handoff()
    capture = copy.deepcopy(data["capture"])
    capture["bytes_per_pixel"] = 2
    capture["pixel_format"] = "Bayer16_candidate"
    budget = resource_budget(data["hardware"]["camera"]["geometry"], capture, 3000)
    assert not budget["link_budget_pass"]
    assert budget["raw_bytes_per_s"] > 125_000_000
    assert data["resources"]["link_budget_pass"]


def test_storage_thresholds_include_preroll_margin_and_reserve():
    camera = {"pixels_across": 100, "pixels_along": 100, "max_fps": 2, "pixel_um": 2, "focal_mm": 20}
    capture = {"requested_fps": 2, "bytes_per_pixel": 1, "link_bits_per_s": 1_000_000, "link_utilisation_limit": .8,
               "warmup_s": 5, "postroll_s": 1, "capacity_margin_fraction": .25,
               "free_space_reserve_bytes": 1000, "available_storage_bytes": 401000,
               "sustained_write_bytes_per_s": 25000}
    budget = resource_budget(camera, capture, 10)
    assert budget["minimum_free_storage_bytes"] == 401000
    assert budget["storage_capacity_pass"] and budget["storage_throughput_pass"]
    capture["available_storage_bytes"] -= 1
    capture["sustained_write_bytes_per_s"] -= 1
    budget = resource_budget(camera, capture, 10)
    assert not budget["storage_capacity_pass"] and not budget["storage_throughput_pass"]


def test_cad_to_mapping_frame_uses_explicit_origin_and_units():
    assert cad_point_to_flu_m([150, 20, -30], [100, 10, 0]) == [-.05, -.01, -.03]
    with pytest.raises(ValueError):
        cad_point_to_flu_m([float("nan"), 0, 0], [0, 0, 0])


@pytest.mark.parametrize("value", [-1, 0, float("nan"), float("inf"), True])
def test_reject_invalid_acquisition_rate(value):
    data = build_handoff()
    data["capture"]["requested_fps"] = value
    with pytest.raises(ValueError):
        validate_handoff(data)


def test_reject_stale_derived_budget_or_false_qualification():
    data = build_handoff()
    data["capture"]["bytes_per_pixel"] = 2
    data["capture"]["pixel_format"] = "Bayer16_candidate"
    with pytest.raises(ValueError, match="resources differ"):
        validate_handoff(data)
    data = build_handoff()
    data["survey_ready"] = True
    with pytest.raises(ValueError, match="survey_ready"):
        validate_handoff(data)


@pytest.mark.parametrize("path,value", [
    (("hardware", "camera", "calibration_state"), "measured"),
    (("navigation", "flight_gnss_independent"), False),
    (("mission", "operator_review"), "approved"),
    (("compatibility", "survey_plan_supported_on_inspected_branch"), True),
])
def test_nested_false_qualification_is_rejected(path, value):
    data = build_handoff()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match="Handoff schema"):
        validate_handoff(data)


def test_missing_review_identity_and_pixel_mode_mismatch_are_rejected():
    data = build_handoff()
    del data["consumer"]["reviewed_on"]
    with pytest.raises(ValueError, match="reviewed_on"):
        validate_handoff(data)
    data = build_handoff()
    data["capture"]["bytes_per_pixel"] = 0.1
    with pytest.raises(ValueError, match="pixel_format"):
        validate_handoff(data)


def test_camera_profile_matches_selected_input_geometry():
    handoff = build_handoff()
    camera = handoff["hardware"]["camera"]["geometry"]
    qgc = camera_profile(handoff)["qgc_custom_camera"]
    assert qgc["ImageWidth"] == camera["pixels_across"]
    assert qgc["MinTriggerInterval"] == 1 / handoff["capture"]["requested_fps"]
    assert qgc["SensorWidth"] == round(camera["pixels_across"] * camera["pixel_um"] / 1000, 2)


def test_export_is_sealed_reproducible_and_refuses_overwrite(tmp_path):
    paths = [tmp_path / "a", tmp_path / "b"]
    for path in paths:
        export_integration(path)
        hashes = (path / "SHA256SUMS").read_text().splitlines()
        for line in hashes:
            digest, name = line.split("  ")
            assert hashlib.sha256((path / name).read_bytes()).hexdigest() == digest
        registry = json.loads((path / "platform_registry.json").read_text())
        assert registry["existing_oak_px4"]["capture_supported"]
        assert not registry["survey_wing_candidate"]["capture_supported"]
        mounting = json.loads((path / "mounting_reference.json").read_text())
        assert mounting["camera_optical_centre_in_cad_mm"] is None
    for name in export_file_names(paths[0]):
        assert (paths[0] / name).read_bytes() == (paths[1] / name).read_bytes()
    with pytest.raises(FileExistsError):
        export_integration(paths[0])


def export_file_names(path):
    return sorted(p.name for p in path.iterdir())


def test_schema_is_valid_and_accepts_export_when_jsonschema_available():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "integration/handoff.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(build_handoff(), schema)
