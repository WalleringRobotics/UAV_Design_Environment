"""Versioned, offline design handoff to Wallering's mapping repository.

The Basler/ArduPilot wing does not match that repository's OAK/PX4 runtime.
Export engineering inputs and explicit blockers, never a fabricated recording,
measured calibration, or flyable plan. This module needs no CAD or ROS runtime.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "wallering.uav-mapping-handoff/v1"


def _number(value, name, *, minimum=0.0, strict=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < minimum or (strict and value == minimum):
        raise ValueError(f"{name} must be {'greater than' if strict else 'at least'} {minimum}")
    return value


def _fraction(value, name, *, allow_zero=True):
    _number(value, name, strict=not allow_zero)
    if value >= 1:
        raise ValueError(f"{name} must be less than 1")
    return value


def cad_point_to_flu_m(point_mm, body_origin_mm):
    """Convert x-aft/y-right/z-up CAD datums to body FLU relative to a known origin.

    This is a coordinate conversion only, never an optical-centre calibration.
    An explicit body origin prevents silently equating lens and FCU origins.
    """
    if len(point_mm) != 3 or len(body_origin_mm) != 3:
        raise ValueError("CAD point and body origin require three coordinates")
    for value in [*point_mm, *body_origin_mm]:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("CAD coordinates must be finite numbers")
    return [sign * (p - o) / 1000 for sign, p, o in zip((-1, -1, 1), point_mm, body_origin_mm)]


def resource_budget(camera, capture, duration_s):
    """Conservative uncompressed payload estimate; no compression/throughput guarantee."""
    for key in ("pixels_across", "pixels_along"):
        if type(camera[key]) is not int or camera[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    for key in ("max_fps", "pixel_um", "focal_mm"):
        _number(camera[key], key)
    for key in ("bytes_per_pixel", "link_bits_per_s"):
        _number(capture[key], key)
    requested_fps = _number(capture["requested_fps"], "requested_fps")
    if requested_fps > camera["max_fps"]:
        raise ValueError("requested_fps exceeds the candidate camera's maximum rate")
    utilisation = _fraction(capture["link_utilisation_limit"], "link_utilisation_limit", allow_zero=False)
    margin = _number(capture["capacity_margin_fraction"], "capacity_margin_fraction", strict=False)
    duration = _number(duration_s, "survey_duration_s")
    warmup = _number(capture["warmup_s"], "warmup_s", strict=False)
    postroll = _number(capture["postroll_s"], "postroll_s", strict=False)
    reserve = _number(capture["free_space_reserve_bytes"], "free_space_reserve_bytes", strict=False)
    bytes_per_frame = camera["pixels_across"] * camera["pixels_along"] * capture["bytes_per_pixel"]
    rate = bytes_per_frame * requested_fps
    minimum_write = rate * (1 + margin)
    minimum_capacity = math.ceil((duration + warmup + postroll) * minimum_write + reserve)
    available = capture["available_storage_bytes"]
    sustained = capture["sustained_write_bytes_per_s"]
    for name, value in (("available_storage_bytes", available), ("sustained_write_bytes_per_s", sustained)):
        if value is not None:
            _number(value, name, strict=False)
    return {
        "budget_rate_hz": requested_fps,
        "raw_bytes_per_frame": bytes_per_frame,
        "raw_bytes_per_s": rate,
        "capture_window_with_preroll_s": duration + warmup + postroll,
        "minimum_sustained_write_bytes_per_s": minimum_write,
        "minimum_free_storage_bytes": minimum_capacity,
        "minimum_free_storage_gib": minimum_capacity / 1024**3,
        "link_payload_budget_bytes_per_s": capture["link_bits_per_s"] / 8 * utilisation,
        "link_budget_pass": rate <= capture["link_bits_per_s"] / 8 * utilisation,
        "storage_capacity_pass": None if available is None else available >= minimum_capacity,
        "storage_throughput_pass": None if sustained is None else sustained >= minimum_write,
        "basis": "Full configured camera rate; uncompressed selected pixel format; capacity margin includes unmodelled telemetry/container overhead. Verify on hardware.",
    }


def survey_geometry(camera, survey, speed, requested_fps=None):
    _number(survey["agl_m"], "agl_m")
    _number(survey["exposure_s"], "exposure_s")
    _number(survey["blur_limit_px"], "blur_limit_px")
    _number(speed, "max_ground_speed_m_s")
    for field in ("forward_overlap", "side_overlap"):
        _fraction(survey[field], field)
    gsd = camera["pixel_um"] * 1e-3 * survey["agl_m"] / camera["focal_mm"]
    footprint = camera["pixels_along"] * gsd
    spacing = footprint * (1 - survey["forward_overlap"])
    return {
        "gsd_m_per_px": gsd,
        "across_track_footprint_m": camera["pixels_across"] * gsd,
        "along_track_footprint_m": footprint,
        "line_spacing_m": camera["pixels_across"] * gsd * (1 - survey["side_overlap"]),
        "trigger_spacing_m": spacing,
        "required_trigger_hz": speed / spacing,
        "forward_motion_blur_px": speed * survey["exposure_s"] / gsd,
        "frame_rate_pass": speed / spacing <= (camera["max_fps"] if requested_fps is None else requested_fps),
        "blur_pass": speed * survey["exposure_s"] / gsd <= survey["blur_limit_px"] * (1 + 1e-12),
        "basis": "Nadir flat-ground pinhole estimate at stated AGL; nominal lens, no terrain/attitude/wind/turn allowance. GSD is not accuracy.",
    }


def validate_handoff(data):
    """Validate identity, units and re-derived resource/geometry results.

    Returns engineering readiness without permitting a design export to claim
    survey qualification. It is deliberately independent of JSON Schema tooling.
    """
    required = {"schema", "schema_version", "status", "platform", "consumer", "source_files",
                "hardware", "mission", "capture", "navigation", "geometry", "resources",
                "compatibility", "survey_ready"}
    if not isinstance(data, dict) or required - data.keys():
        raise ValueError(f"Missing handoff fields: {sorted(required - data.keys()) if isinstance(data, dict) else 'object required'}")
    if data["schema"] != SCHEMA or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported handoff schema")
    if data["platform"] != "survey_wing" or data["status"] != "design_proposal":
        raise ValueError("This exporter supports survey_wing design proposals only")
    if data["survey_ready"] is not False:
        raise ValueError("A generated design proposal cannot claim survey_ready")
    consumer = data["consumer"]
    if consumer["repository"] != "WalleringRobotics/mapping_functionality":
        raise ValueError("Unexpected consumer repository")
    for key in ("inspected_main_revision", "inspected_survey_branch_revision", "inspected_processing_branch_revision", "inspected_plan_branch_revision"):
        if not re.fullmatch("[0-9a-f]{40}", consumer[key]):
            raise ValueError(f"{key} must be an immutable Git revision")
    if not data["source_files"]:
        raise ValueError("Source fingerprints are required")
    for path, digest in data["source_files"].items():
        if Path(path).is_absolute() or ".." in Path(path).parts or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("Source fingerprints require relative paths and SHA-256")
    if data["navigation"]["autopilot_family"] != "ArduPilot" or data["navigation"]["vehicle_type"] != "fixed_wing":
        raise ValueError("Survey-wing navigation must identify ArduPilot fixed wing explicitly")
    mission, camera = data["mission"], data["hardware"]["camera"]["geometry"]
    resources = resource_budget(camera, data["capture"], mission["survey_duration_s"])
    geometry = survey_geometry(camera, mission, mission["max_ground_speed_m_s"], data["capture"]["requested_fps"])
    for key, calculated in (("resources", resources), ("geometry", geometry)):
        if data[key] != calculated:
            raise ValueError(f"{key} differ from the supplied inputs; regenerate the handoff")
    blockers = ["Selected Basler candidate needs a GigE adapter; existing OAK capture remains supported",
                "ArduPilot Plane mission checking is not supported by inspected survey branch",
                "F9P exposure-event association and raw PPK ingestion require a new adapter",
                "Optical centre, antenna ARP, timing and camera calibration remain unmeasured",
                "Site boundary, reference datum, control/checkpoints and operator review are pending"]
    for label, value in (("link payload", resources["link_budget_pass"]),
                         ("storage capacity", resources["storage_capacity_pass"]),
                         ("storage throughput", resources["storage_throughput_pass"]),
                         ("camera frame rate", geometry["frame_rate_pass"]),
                         ("forward-motion blur", geometry["blur_pass"])):
        if value is not True:
            blockers.append(f"{label}: {'unmeasured' if value is None else 'fails the requested design budget'}")
    if data["compatibility"]["capture_supported_on_inspected_main"] is not False:
        raise ValueError("Basler compatibility cannot be asserted for the inspected OAK runtime")
    return {"schema_valid": True, "survey_ready": False, "blocking_reasons": blockers,
            "link_budget_pass": resources["link_budget_pass"],
            "geometry_pass": geometry["frame_rate_pass"] and geometry["blur_pass"]}


def build_handoff(root=ROOT, profile_path=None, design_summary=None):
    root = Path(root)
    profile_path = Path(profile_path) if profile_path else root / "integration/mapping_profile.yaml"
    paths = [profile_path, root / "platforms/survey_wing/design_point.yaml",
             root / "platforms/survey_wing/electronics.yaml", root / "payload/survey_cage.yaml",
             root / "mission/mission_params.yaml"]
    profile, design, electronics, payload, _mission = [yaml.safe_load(p.read_text()) for p in paths]
    if profile["schema_version"] != 1 or profile["platform"] != "survey_wing":
        raise ValueError("Unsupported integration profile")
    survey = copy.deepcopy(design["survey"])
    camera = survey.pop("camera")
    capture = copy.deepcopy(profile["capture"])
    # Validate camera and basic resource inputs before using them in divisions.
    resource_budget(camera, capture, 1)
    survey_geometry(camera, survey, 1)
    gsd = camera["pixel_um"] * 1e-3 * survey["agl_m"] / camera["focal_mm"]
    speed_bound = min(camera["pixels_along"] * gsd * (1 - survey["forward_overlap"]) * capture["requested_fps"] * 0.8,
                      survey["blur_limit_px"] * gsd / survey["exposure_s"])
    mission = {**survey, **copy.deepcopy(profile["mission"])}
    mission["max_ground_speed_m_s"] = mission["max_ground_speed_m_s"] if mission["max_ground_speed_m_s"] is not None else speed_bound
    mission["survey_duration_s"] = mission["survey_duration_s"] if mission["survey_duration_s"] is not None else design["requirements"]["endurance_min"] * 60
    mission["duration_basis"] = "requested integration window; does not establish achieved aircraft endurance"
    mission["speed_basis"] = "explicit profile ground speed or nominal camera/blur upper bound; not commanded airspeed"
    members = payload["cage"]["members"]
    hardware = {
        "camera": {"part": members["camera"]["part"], "geometry": camera, "selection_policy": profile["camera_policy"],
                   "calibration_state": "nominal_design_only", "confirm": members["camera"].get("confirm")},
        "lens": members["lens"]["part"],
        "flight_controller": electronics["components"]["flight_controller"]["part"],
        "flight_gnss": electronics["components"]["flight_gnss"]["part"],
        "survey_receiver": members["gnss_receiver"]["part"],
        "compute_variants": {key: {"part": value["part"], **profile["compute"][key]} for key, value in payload["compute"].items()},
        "camera_and_antenna_on_same_rigid_cage": True,
    }
    sources = {}
    for path in paths:
        try:
            name = str(path.resolve().relative_to(root.resolve()))
        except ValueError as exc:
            raise ValueError("All source inputs must reside inside the design root") from exc
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    data = {
        "schema": SCHEMA, "schema_version": 1, "status": "design_proposal", "platform": "survey_wing",
        "survey_ready": False, "consumer": profile["consumer"], "source_files": sources,
        "hardware": hardware, "mission": mission, "capture": capture, "navigation": profile["navigation"],
        "geometry": survey_geometry(camera, mission, mission["max_ground_speed_m_s"], capture["requested_fps"]),
        "resources": resource_budget(camera, capture, mission["survey_duration_s"]),
        "compatibility": {"capture_supported_on_inspected_main": False,
                          "survey_plan_supported_on_inspected_branch": False,
                          "existing_offline_engines_reusable_after_validated_import": True},
    }
    if design_summary is not None:
        data["design_analysis"] = copy.deepcopy(design_summary)
    validate_handoff(data)
    return data


def camera_profile(handoff):
    camera = handoff["hardware"]["camera"]["geometry"]
    return {
        "schema_version": 1, "name": handoff["hardware"]["camera"]["part"],
        "stream": "rgb", "profile_resolution": f"{camera['pixels_across']}x{camera['pixels_along']}",
        "qgc_custom_camera": {
            "SensorWidth": round(camera["pixels_across"] * camera["pixel_um"] / 1000, 2),
            "SensorHeight": round(camera["pixels_along"] * camera["pixel_um"] / 1000, 2),
            "ImageWidth": camera["pixels_across"], "ImageHeight": camera["pixels_along"],
            "FocalLength": camera["focal_mm"], "Landscape": True, "FixedOrientation": True,
            "MinTriggerInterval": 1 / handoff["capture"]["requested_fps"],
        },
        "derivation": {"pixel_pitch_um": camera["pixel_um"], "source": "platforms/survey_wing/design_point.yaml; nominal design, not camera calibration"},
        "limitations": ["Camera definition only; PR #26 rejects ArduPilot/fixed-wing plans and reads OAK ROS profiles",
                        "Verify ordered SKU, pixel format, full-resolution triggered frame rate, focus and actual intrinsics",
                        "Custom-camera field format reviewed against mapping PR #26; this is not a QGC mission"],
    }


def export_integration(output_dir, *, root=ROOT, design_summary=None):
    """Write a fresh atomic integration artifact directory; never overwrite evidence."""
    root, output_dir = Path(root), Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"Integration output already exists: {output_dir}")
    handoff = build_handoff(root, design_summary=design_summary)
    report = validate_handoff(handoff)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".mapping-export-", dir=output_dir.parent))
    try:
        values = {"mapping_handoff.json": handoff, "validation.json": report,
                  "platform_registry.json": {
                      "schema_version": 1,
                      "existing_oak_px4": {
                          "role": "existing physical platform; preserve its runtime and qualification history",
                          "camera": "Luxonis OAK-D", "autopilot": "PX4", "compute": "Jetson Orin Nano",
                          "capture_supported": True, "survey_ready": False,
                          "qualification_basis": "mapping main and PR #25 report; no local hardware verification performed",
                          "configuration_path": "mapping_functionality/configs/oakd-ros.yaml",
                          "image_fps": 2, "oak_gyro_hz": 200,
                      },
                      "survey_wing_candidate": {
                          "role": "new dedicated fixed-wing platform",
                          "preferred_camera": handoff["hardware"]["camera"]["part"],
                          "camera_substitution_allowed": True, "autopilot": "ArduPilot Plane",
                          "compute_variants": ["orin", "cm5"], "capture_supported": False,
                          "survey_ready": False, "handoff": "mapping_handoff.json",
                      },
                  },
                  "camera_profile.json": camera_profile(handoff),
                  "mounting_reference.json": {
                      "schema_version": 1, "status": "unmeasured", "survey_ready": False,
                      "cad_axes": "x aft, y right, z up; millimetres",
                      "mapping_body_axes": "x forward, y left, z up; metres",
                      "cad_to_flu_rotation": [[-1, 0, 0], [0, -1, 0], [0, 0, 1]],
                      "body_origin_in_cad_mm": None, "camera_optical_centre_in_cad_mm": None,
                      "antenna_arp_in_cad_mm": None, "translation_covariance_m2": None,
                      "note": "Cage lens-front datum and component envelope positions are not optical-centre or antenna-ARP measurements. Current mapping rig parser accepts OAK frame names only.",
                  }}
        for name, value in values.items():
            (staging / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        for source in (root / "docs/software_spec.md", root / "integration/handoff.schema.json"):
            shutil.copyfile(source, staging / source.name)
        checksum_paths = sorted(p for p in staging.iterdir() if p.is_file())
        (staging / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in checksum_paths))
        staging.rename(output_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"path": str(output_dir), "files": sorted(p.name for p in output_dir.iterdir()), **report}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = export_integration(args.output)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
