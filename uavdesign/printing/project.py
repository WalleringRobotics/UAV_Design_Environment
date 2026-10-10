"""A bounded project facade shared by CLI and MCP.

Project paths are repository-relative. Plans are keyed by the source manifest
and project settings; changing either produces a new directory. Slicing is a
separate operation and never uploads or starts a printer job.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import zipfile

import yaml


DEFAULT_PROJECT = "print_projects/survey_wing/project.yaml"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PrintProject:
    _operation_lock = threading.Lock()

    def __init__(self, root: Path, project_path: str = DEFAULT_PROJECT):
        self.root = root.resolve()
        self.path = self.local_path(project_path)
        self.config = yaml.safe_load(self.path.read_text())
        self._config_sha256 = digest(self.path)
        if not isinstance(self.config, dict) or self.config.get("schema_version") != "1.0":
            raise ValueError("Unsupported print project schema")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.config.get("name", "")):
            raise ValueError("Project name must be a short lowercase identifier")
        from .planner import normalize_project
        self.config = normalize_project(self.config)
        if self.config.get("workflow", {}).get("start_print_requires_user_confirmation") is not True:
            raise ValueError("This project requires user confirmation before every print start")
        self.parts_dir = self.local_path(self.config["parts_dir"])
        self.output_dir = self.local_path(self.config["output_dir"])
        outputs = self.root / "outputs" / "print_projects"
        if not self.output_dir.is_relative_to(outputs) or self.output_dir == outputs:
            raise ValueError("Print output must be a project directory under outputs/print_projects")
        if self.parts_dir == self.output_dir or self.parts_dir.is_relative_to(self.output_dir):
            raise ValueError("Print outputs cannot contain the source parts")
        self._lock = self._operation_lock

    def _ensure_current(self) -> None:
        if digest(self.path) != self._config_sha256:
            raise ValueError("Project configuration changed; reload the project before continuing")

    def local_path(self, value: str) -> Path:
        if not isinstance(value, str) or not value or Path(value).is_absolute():
            raise ValueError("Expected a nonempty repository-relative path")
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Path escapes the repository")
        return path

    def plan_id(self) -> str:
        self._ensure_current()
        fingerprint = {
            "manifest_sha256": digest(self.parts_dir / "manifest.json"),
            "project": self.config,
            "planner": {p.name: digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))
                        if p.name in {"planner.py", "three_mf.py"}},
            "footprint_helper_sha256": digest(Path(__file__).parents[1] / "fab" / "printer.py"),
        }
        return hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()[:20]

    def plan_dir(self) -> Path:
        return self.output_dir / "plans" / self.plan_id()

    def inventory(self) -> dict:
        self._ensure_current()
        from .planner import load_inventory
        return load_inventory(self.parts_dir)

    def status(self) -> dict:
        self._ensure_current()
        executable = self.config.get("slicer", {}).get("executable", "prusa-slicer")
        presets = self.config.get("slicer", {}).get("presets", {})
        return {
            "name": self.config["name"],
            "project_file": str(self.path.relative_to(self.root)),
            "parts_available": (self.parts_dir / "manifest.json").is_file(),
            "printer": self.config["printer"],
            "slicer_executable": executable,
            "slicer_available": shutil.which(executable) is not None,
            "presets_available": {name: self.local_path(path).is_file() for name, path in presets.items()},
            "prusalink_url_configured": bool(self.connection().get("url")),
            "prusalink_auth_configured": bool(self.connection().get("username") and self.connection().get("password")),
            "physical_print_start": "requires explicit user confirmation; no start tool is exposed",
            "printables_required": False,
        }

    def export(self) -> dict:
        from .planner import export_plan
        with self._lock:
            out = self.plan_dir()
            plan = export_plan(self.parts_dir, self.config, out)
            (out / "project.yaml").write_text(yaml.safe_dump(self.config, sort_keys=False))
            checksums = {str(p.relative_to(out)): digest(p) for p in sorted(out.rglob("*"))
                         if p.is_file() and p.name != "SHA256SUMS"}
            (out / "SHA256SUMS").write_text("".join(f"{sha}  {name}\n" for name, sha in checksums.items()))
            archive = out.with_suffix(".zip")
            fd, tmp_name = tempfile.mkstemp(prefix=".plan-", suffix=".zip", dir=out.parent)
            os.close(fd)
            try:
                with zipfile.ZipFile(tmp_name, "w", compression=zipfile.ZIP_DEFLATED) as z:
                    for path in sorted(out.rglob("*")):
                        if path.is_file():
                            z.write(path, arcname=f"{self.config['name']}/{path.relative_to(out)}")
                os.replace(tmp_name, archive)
            finally:
                Path(tmp_name).unlink(missing_ok=True)
            return {"plan_id": out.name, "output_dir": str(out), "archive": str(archive),
                    "plan": plan}

    def read_plan(self) -> dict:
        path = self.plan_dir() / "print_plan.json"
        if not path.is_file():
            raise ValueError("No plan for the current source and settings; run plan_prints first")
        # Revalidate source STL digests even when the manifest itself has not changed.
        inventory = self.inventory()
        plan = json.loads(path.read_text())
        if plan.get("manifest_sha256") != inventory["manifest_sha256"] or plan.get("project") != self.config:
            raise ValueError("Plan does not match the current source and project settings")
        sums = self.plan_dir() / "SHA256SUMS"
        if not sums.is_file():
            raise ValueError("Plan is incomplete; regenerate it")
        expected_files = {"print_plan.json", "project.yaml", "queue.html"}
        expected_files.update(p["files"][key] for p in plan["plates"] for key in ("3mf", "svg"))
        entries = [line.split("  ", 1) for line in sums.read_text().splitlines()]
        if (any(len(entry) != 2 for entry in entries) or len(entries) != len(expected_files)
                or {entry[1] for entry in entries} != expected_files):
            raise ValueError("Plan checksum coverage is incomplete; regenerate the plan")
        for expected, name in entries:
            target = (self.plan_dir() / name).resolve()
            if not target.is_relative_to(self.plan_dir()) or not target.is_file() or digest(target) != expected:
                raise ValueError("Generated plan files changed; regenerate the plan before slicing")
        return plan

    def slice(self, plate_id: str, *, execute: bool = False) -> dict:
        from .slicer import prepare_slice, slice_plate
        if not re.fullmatch(r"plate_[0-9]{3}", plate_id):
            raise ValueError("Expected a plate identifier such as plate_001")
        with self._lock:
            plan = self.read_plan()
            plate = next((p for p in plan["plates"] if p["id"] == plate_id), None)
            if plate is None:
                raise ValueError("Plate does not belong to the current plan")
            profile = plate["profile"]
            preset = self.config.get("slicer", {}).get("presets", {}).get(profile)
            if not preset or not self.local_path(preset).is_file():
                return {"state": "blocked", "plate_id": plate_id, "reason": "missing_preset",
                        "required_profile": profile, "preset_path": preset,
                        "required_settings": plate["settings"],
                        "next_step": "Export a complete PrusaSlicer configuration for this printer, filament and print profile"}
            machine = dict(self.config["printer"])
            if plate["settings"].get("material") == "asa_cf" and machine.get("hardened_nozzle_installed") is not True:
                return {"state": "blocked", "plate_id": plate_id, "reason": "hardened_nozzle_not_confirmed"}
            plate_path = self.plan_dir() / plate["files"]["3mf"]
            if not plate_path.resolve().is_relative_to(self.plan_dir()):
                raise ValueError("Invalid plate path in plan")
            # New settings never overwrite G-code from a different profile revision.
            preset_path = self.local_path(preset)
            out = self.output_dir / "slices" / self.plan_id() / digest(preset_path)[:20] / f"{plate_id}.gcode"
            action = slice_plate if execute else prepare_slice
            result = action(plate_path, [preset_path], out,
                            self.config["slicer"]["executable"],
                            machine=machine, expected_settings=plate["settings"])
            if execute:
                report = out.with_suffix(".json")
                report.write_text(json.dumps(result, indent=2) + "\n")
            return result

    def connection(self) -> dict:
        self._ensure_current()
        path = self.local_path(".local/printing/connection.json")
        config = json.loads(path.read_text()) if path.exists() else {}
        # Environment credentials override the ignored local file, never enter exports.
        return {key: os.environ.get(env) or config.get(key) for key, env in {
            "url": "PRUSALINK_URL", "username": "PRUSALINK_USERNAME", "password": "PRUSALINK_PASSWORD"
        }.items()}

    def printer_status(self) -> dict:
        from .prusalink import PrusaLink
        config = self.connection()
        if not all(config.values()):
            return {"state": "not_configured", "url_configured": bool(config.get("url")),
                    "auth_configured": bool(config.get("username") and config.get("password")),
                    "next_step": "Set PrusaLink credentials using the local configure-printer command; never paste them into chat"}
        return PrusaLink(config["url"], config["username"], config["password"]).status_snapshot()
