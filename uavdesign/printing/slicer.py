"""Validated, offline PrusaSlicer adapter for planned, millimetre 3MF plates.

Uses the official CLI options defined in PrusaSlicer 2.9.6 PrintConfig.cpp:
https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.6/src/libslic3r/PrintConfig.cpp
No profile is invented: callers supply one complete exported configuration.
Slicing never uploads G-code, starts a printer, or executes profile post-processors.
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile


class SlicerError(RuntimeError):
    """A missing dependency, incompatible profile, or failed slicing result."""


DEFAULT_MACHINE = {"model": "COREONE", "bed_mm": [250, 220, 270], "nozzle_diameter_mm": 0.4}
_REQUIRED = {
    "printer_model", "printer_settings_id", "print_settings_id", "filament_settings_id",
    "bed_shape", "max_print_height", "nozzle_diameter", "gcode_flavor",
    "filament_type", "filament_diameter", "filament_density", "extrusion_multiplier",
    "temperature", "first_layer_temperature", "bed_temperature", "first_layer_bed_temperature",
    "layer_height", "first_layer_height", "perimeters", "fill_density", "fill_pattern",
    "extrusion_width", "support_material", "start_gcode", "end_gcode", "post_process",
    "perimeter_speed", "infill_speed", "travel_speed", "retract_length",
}
_CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _number(value: str, key: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise SlicerError(f"Setting {key} must be a single numeric value") from None
    if not math.isfinite(number):
        raise SlicerError(f"Setting {key} must be finite")
    return number


def _settings(path: Path) -> dict[str, str]:
    if not path.is_file() or path.stat().st_size > 2_000_000:
        raise SlicerError("Supply a complete exported PrusaSlicer INI (maximum 2 MB)")
    settings = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise SlicerError("Cannot read the exported configuration as UTF-8") from None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") or "=" not in line:
            raise SlicerError("Use File > Export > Export Config; sectioned preset bundles are unsupported")
        key, value = (item.strip() for item in line.split("=", 1))
        if key in settings:
            raise SlicerError(f"Duplicate exported setting: {key}")
        settings[key] = value
    missing = sorted(_REQUIRED - settings.keys())
    if missing:
        raise SlicerError("Incomplete exported configuration; missing " + ", ".join(missing))
    if settings["post_process"].strip('" '):
        raise SlicerError("External post-processing commands are disabled")
    for key, value in settings.items():
        if any(token in key.lower() for token in ("password", "apikey", "api_key", "token")) and value.strip('" '):
            raise SlicerError("Remove connection credentials from the slicing configuration")
    return settings


def _machine(settings: dict, machine: dict) -> dict:
    try:
        bed = [_number(str(item), "bed_mm") for item in machine["bed_mm"]]
        nozzle = _number(str(machine.get("nozzle_diameter_mm", machine.get("nozzle_mm"))), "nozzle diameter")
        model = str(machine["model"])
    except (KeyError, TypeError):
        raise SlicerError("Machine requires model, three bed_mm dimensions and nozzle_diameter_mm") from None
    if len(bed) != 3 or min(bed) <= 0 or nozzle <= 0 or not model:
        raise SlicerError("Invalid target machine dimensions")
    if settings["printer_model"].strip('"') != model:
        raise SlicerError("Exported printer_model does not match the target machine")
    if not math.isclose(_number(settings["nozzle_diameter"], "nozzle_diameter"), nozzle, abs_tol=1e-6):
        raise SlicerError("Exported nozzle diameter does not match the target machine")
    try:
        polygon = [[float(v) for v in point.split("x")] for point in settings["bed_shape"].split(",")]
    except ValueError:
        raise SlicerError("Unsupported bed_shape; a rectangular bed is required") from None
    expected = {(0., 0.), (bed[0], 0.), (bed[0], bed[1]), (0., bed[1])}
    if len(polygon) != 4 or any(len(p) != 2 for p in polygon) or set(map(tuple, polygon)) != expected:
        raise SlicerError("Exported bed_shape does not match the planned rectangular bed")
    if not math.isclose(_number(settings["max_print_height"], "max_print_height"), bed[2], abs_tol=1e-6):
        raise SlicerError("Exported print height does not match the target machine")
    for key in ("filament_diameter", "filament_density", "extrusion_multiplier", "layer_height"):
        if _number(settings[key], key) <= 0:
            raise SlicerError(f"Setting {key} must be positive")
    return {"model": model, "bed_mm": bed, "nozzle_diameter_mm": nozzle}


def _expected(settings: dict, expected: dict | None) -> list[str]:
    notes = ["Filament flow, temperatures and support regions require review against the actual material and part."]
    if not expected:
        notes.append("No part-specific wall, infill or material requirements were provided.")
        return notes
    for source, target in (("perimeters", "perimeters"), ("layer_height_mm", "layer_height"),
                           ("extrusion_width_mm", "extrusion_width")):
        if source in expected and not math.isclose(_number(settings[target], target), float(expected[source]), abs_tol=1e-6):
            raise SlicerError(f"Exported {target} does not match planned {source}")
    if "extrusion_width_mm" in expected:
        for key in ("perimeter_extrusion_width", "external_perimeter_extrusion_width"):
            width = _number(settings.get(key, "0"), key)
            if width and not math.isclose(width, float(expected["extrusion_width_mm"]), abs_tol=1e-6):
                raise SlicerError(f"Exported {key} overrides the planned wall width")
    if "infill_fraction" in expected:
        density = _number(settings["fill_density"].rstrip("%"), "fill_density") / 100
        if not math.isclose(density, float(expected["infill_fraction"]), abs_tol=1e-6):
            raise SlicerError("Exported fill_density does not match planned infill_fraction")
    if "infill" in expected and settings["fill_pattern"] != expected["infill"]:
        raise SlicerError("Exported fill_pattern does not match the planned infill")
    support = str(expected.get("supports", "")).lower()
    if support == "none" and settings["support_material"] != "0":
        raise SlicerError("Support material must be disabled for this plate")
    if "tree" in support:
        if settings["support_material"] != "1" or settings.get("support_material_style") != "organic":
            raise SlicerError("This plate requires organic supports in the exported profile")
        if "outer" in support:
            notes.append("Outer-only support placement cannot be established from global INI settings; inspect the toolpath preview.")
    if "material" in expected:
        material = str(expected["material"]).lower()
        nominal = {"lw_asa": "ASA", "asa_cf": "ASA", "asa": "ASA", "petg": "PETG"}.get(material)
        if nominal and settings["filament_type"].strip('"').upper() != nominal:
            raise SlicerError("Exported filament_type does not match the planned material family")
        identity = re.sub(r"[^a-z0-9]", "", settings["filament_settings_id"].lower())
        if material in {"lw_asa", "asa_cf"} and material.replace("_", "") not in identity:
            raise SlicerError("Use an explicitly named LW-ASA or ASA-CF filament preset matching the plate")
    return notes


def _plate(path: Path, bed: list[float]) -> dict:
    if path.suffix.lower() != ".3mf" or not path.is_file():
        raise SlicerError("Supply an existing geometry-only planned .3mf plate")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 100 or sum(i.file_size for i in infos) > 250_000_000:
                raise SlicerError("3MF exceeds the supported archive size")
            # Imported projects may embed scripts/configuration. The planner emits
            # only core meshes. Explicitly reject settings-bearing third-party 3MF.
            names = [i.filename for i in infos]
            if any(name.lower().startswith("metadata/") for name in names):
                raise SlicerError("Use a geometry-only planned plate; embedded project settings are unsupported")
            models = [name for name in names if name.lower().endswith(".model")]
            if len(models) != 1:
                raise SlicerError("3MF must contain exactly one core model")
            root = ET.fromstring(archive.read(models[0]))
    except (zipfile.BadZipFile, ET.ParseError, KeyError, OSError):
        raise SlicerError("Cannot read the planned 3MF geometry") from None
    if root.tag != _CORE + "model" or root.get("unit", "millimeter") != "millimeter":
        raise SlicerError("3MF must use millimetres and the core model format")
    objects = {obj.get("id"): obj for obj in root.findall(f"{_CORE}resources/{_CORE}object")}
    items = root.findall(f"{_CORE}build/{_CORE}item")
    if not items:
        raise SlicerError("3MF plate has no build items")
    low, high, count = [math.inf] * 3, [-math.inf] * 3, 0
    for item in items:
        obj = objects.get(item.get("objectid"))
        if obj is None or obj.find(_CORE + "components") is not None:
            raise SlicerError("3MF must contain direct mesh objects, not component assemblies")
        try:
            transform = [float(v) for v in item.get("transform", "1 0 0 0 1 0 0 0 1 0 0 0").split()]
            if len(transform) != 12 or not all(math.isfinite(v) for v in transform):
                raise ValueError
            vertices = obj.findall(f"{_CORE}mesh/{_CORE}vertices/{_CORE}vertex")
            triangles = obj.findall(f"{_CORE}mesh/{_CORE}triangles/{_CORE}triangle")
            if len(vertices) < 4 or len(triangles) < 4:
                raise ValueError
            for vertex in vertices:
                xyz = [float(vertex.attrib[axis]) for axis in "xyz"]
                point = [sum(xyz[i] * transform[i * 3 + j] for i in range(3)) + transform[9 + j] for j in range(3)]
                if not all(math.isfinite(v) for v in point):
                    raise ValueError
                low = [min(low[i], point[i]) for i in range(3)]
                high = [max(high[i], point[i]) for i in range(3)]
                count += 1
        except (ValueError, KeyError):
            raise SlicerError("Invalid mesh or transform in planned 3MF") from None
    if any(low[i] < -1e-4 or high[i] > bed[i] + 1e-4 for i in range(3)):
        raise SlicerError("Planned 3MF geometry exceeds the target print volume")
    return {"build_items": len(items), "vertices": count, "bounds_mm": [low, high]}


def _run(command: list[str], timeout_s: float) -> tuple[int, str]:
    # A file, rather than PIPE, bounds memory even if a broken binary is noisy.
    with tempfile.TemporaryFile() as capture:
        try:
            result = subprocess.run(command, stdout=capture, stderr=subprocess.STDOUT,
                                    timeout=timeout_s, check=False, shell=False)
        except (OSError, subprocess.TimeoutExpired):
            raise SlicerError("PrusaSlicer could not run or exceeded its timeout") from None
        capture.seek(0)
        output = capture.read(2_000_001)
    if len(output) > 2_000_000:
        raise SlicerError("PrusaSlicer diagnostic output exceeds the supported limit")
    return result.returncode, output.decode("utf-8", errors="replace")


def _probe(executable: str) -> dict:
    resolved = shutil.which(executable)
    if not resolved:
        raise SlicerError("PrusaSlicer is unavailable; install it locally and select its executable")
    # PrusaSlicer 2.x reports its version in the --help banner; it does not
    # consistently implement a standalone --version option.
    code, help_text = _run([resolved, "--help"], 15)
    match = re.search(r"PrusaSlicer[-\s]+(\d+\.\d+\.\d+(?:[-+][\w.-]+)?)", help_text)
    if code or not match:
        raise SlicerError("Executable did not identify itself as PrusaSlicer")
    if code or any(flag not in help_text for flag in ("--load", "--dont-arrange", "--export-gcode", "--output", "--config-compatibility")):
        raise SlicerError("Installed PrusaSlicer lacks required planning CLI options")
    code, fff_help = _run([resolved, "--help-fff"], 15)
    if code or any(flag not in fff_help for flag in ("--post-process", "--binary-gcode")):
        raise SlicerError("Installed PrusaSlicer cannot enforce offline text G-code export")
    return {"executable": str(Path(resolved).resolve()), "version": match.group(1),
            "sha256": _sha(Path(resolved))}


def prepare_slice(plate_path: Path, preset_paths: list[Path], output_path: Path,
                  executable: str = "prusa-slicer", *, machine: dict | None = None,
                  expected_settings: dict | None = None) -> dict:
    """Validate inputs and executable, returning a reproducible argv and hashes.

    This performs only local executable help/version probes. It does not slice,
    change an input, contact a printer, or create output directories.
    """
    if len(preset_paths) != 1:
        raise SlicerError("Supply exactly one complete exported PrusaSlicer INI per plate")
    plate, preset, output = Path(plate_path).resolve(), Path(preset_paths[0]).resolve(), Path(output_path).resolve()
    if (output.suffix.lower() != ".gcode" or output.exists() or output in {plate, preset}
            or preset.parent == output.parent or output.is_relative_to(preset)):
        raise SlicerError("Choose a new .gcode output outside the preset directory and input files")
    settings = _settings(preset)
    target = _machine(settings, machine or DEFAULT_MACHINE)
    notes = _expected(settings, expected_settings)
    geometry = _plate(plate, target["bed_mm"])
    binary = _probe(executable)
    command = [binary["executable"], "--load", str(preset), "--config-compatibility", "disable",
               "--dont-arrange", "--post-process", "", "--no-binary-gcode",
               "--export-gcode", "--output", str(output), str(plate)]
    observed = {key: settings[key] for key in sorted(_REQUIRED) if key not in {"start_gcode", "end_gcode", "post_process"}}
    return {"state": "prepared", "sliced": False, "printer_action": "none", "command": command,
            "slicer": binary, "plate": {"path": str(plate), "sha256": _sha(plate), **geometry},
            "preset": {"path": str(preset), "sha256": _sha(preset), "settings": observed},
            "machine": target, "output": str(output), "review_notes": notes}


def _gcode(path: Path, settings: dict) -> dict:
    if not path.is_file() or path.stat().st_size < 100 or path.stat().st_size > 1_000_000_000:
        raise SlicerError("PrusaSlicer produced no usable G-code file")
    moves, layers, metadata, exported = 0, 0, {}, {}
    relative_e, extruder, last_xy = False, 0.0, [None, None]
    with path.open(encoding="utf-8") as stream:
        try:
            for line in stream:
                if line.startswith(";LAYER_CHANGE"):
                    layers += 1
                if line.startswith(";") and "=" in line:
                    key, value = (item.strip() for item in line[1:].split("=", 1))
                    if key in {"printer_model", "nozzle_diameter", "bed_shape", "max_print_height"}:
                        exported[key] = value
                    if key.startswith(("estimated printing time", "filament used")):
                        metadata[key] = value
                code = line.split(";", 1)[0].strip().upper()
                if code == "M82":
                    relative_e = False
                elif code == "M83":
                    relative_e = True
                elif code.startswith(("G0 ", "G1 ", "G2 ", "G3 ", "G92 ")):
                    values = {key: float(value) for key, value in re.findall(r"([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))", code)}
                    if not all(math.isfinite(v) for v in values.values()):
                        raise SlicerError("Non-finite motion in generated G-code")
                    if code.startswith("G92 "):
                        extruder = values.get("E", extruder)
                        continue
                    position = [values.get(axis, last_xy[i]) for i, axis in enumerate("XY")]
                    if "E" in values:
                        delta = values["E"] if relative_e else values["E"] - extruder
                        if delta > 1e-7 and ((position != last_xy and any(axis in values for axis in "XY"))
                                             or code.startswith(("G2 ", "G3 "))):
                            moves += 1
                        extruder = extruder + values["E"] if relative_e else values["E"]
                    last_xy = position
        except (UnicodeError, ValueError):
            raise SlicerError("Generated G-code is not valid UTF-8 text") from None
    if layers < 1 or moves < 4:
        raise SlicerError("Generated G-code has no substantive layer extrusion toolpath")
    if set(exported) != {"printer_model", "nozzle_diameter", "bed_shape", "max_print_height"}:
        raise SlicerError("Generated G-code machine metadata does not match the validated preset")
    target = {"model": settings["printer_model"].strip('"'),
              "bed_mm": [max(float(p.split("x")[0]) for p in settings["bed_shape"].split(",")),
                         max(float(p.split("x")[1]) for p in settings["bed_shape"].split(",")),
                         float(settings["max_print_height"])],
              "nozzle_diameter_mm": float(settings["nozzle_diameter"])}
    _machine({**settings, **exported}, target)
    duration_s = max((sum(float(value) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
                          for value, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([dhms])", text))
                      for key, text in metadata.items() if key.startswith("estimated printing time")), default=0)
    try:
        filament_mm = float(metadata.get("filament used [mm]", "0"))
    except ValueError:
        filament_mm = 0
    if duration_s <= 0 or not math.isfinite(filament_mm) or filament_mm <= 0:
        raise SlicerError("Generated G-code is missing slicer time/material estimates")
    return {"sha256": _sha(path), "bytes": path.stat().st_size, "extrusion_moves": moves,
            "layers": layers, "estimated_time_s": duration_s, "filament_mm": filament_mm,
            "estimates": metadata, "machine_settings": exported}


def slice_plate(plate_path: Path, preset_paths: list[Path], output_path: Path,
                executable: str = "prusa-slicer", *, machine: dict | None = None,
                expected_settings: dict | None = None, timeout_s: float = 300) -> dict:
    """Slice locally and publish a new G-code only after validating its contents."""
    if isinstance(timeout_s, bool) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 3600:
        raise SlicerError("Slicing timeout must be greater than zero and at most 3600 seconds")
    prepared = prepare_slice(plate_path, preset_paths, output_path, executable,
                             machine=machine, expected_settings=expected_settings)
    output = Path(prepared["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".slice-", dir=output.parent) as directory:
        staged = Path(directory) / output.name
        command = list(prepared["command"])
        command[command.index("--output") + 1] = str(staged)
        code, _ = _run(command, timeout_s)
        if code:
            raise SlicerError(f"PrusaSlicer slicing failed with exit status {code}")
        for source in (prepared["plate"], prepared["preset"]):
            if _sha(Path(source["path"])) != source["sha256"]:
                raise SlicerError("A slicing input changed during execution; output discarded")
        result = _gcode(staged, _settings(Path(prepared["preset"]["path"])))
        try:
            # Atomic, exclusive publication on the same filesystem; never clobber.
            os.link(staged, output)
        except FileExistsError:
            raise SlicerError("G-code output appeared during slicing; refusing to overwrite it") from None
    return {**prepared, "state": "sliced_for_review", "sliced": True, "gcode": result,
            "print_ready": None}
