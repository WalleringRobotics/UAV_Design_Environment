"""The review project remains tied to source artifacts, with a real MCP handshake."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tomllib
import zipfile

import pytest
import yaml

from test_print_planner import _inventory, PROJECT
from uavdesign.printing.project import PrintProject
from uavdesign.printing.__main__ import configure_mcp, configure_printer


@pytest.fixture
def project(tmp_path):
    _inventory(tmp_path, [{}, {}])
    config = {**PROJECT, "parts_dir": "source", "output_dir": "outputs/print_projects/test",
              "slicer": {"executable": "missing-prusa-slicer-for-test", "presets": {"shell": ".local/printing/shell.ini"}},
              "workflow": {"start_print_requires_user_confirmation": True}}
    (tmp_path / "project.yaml").write_text(yaml.safe_dump(config))
    return PrintProject(tmp_path, "project.yaml")


def test_export_review_zip_contains_all_layouts_and_checksums(project):
    result = project.export()
    assert result["plan"]["part_count"] == 2
    assert result["plan"]["sliced"] is False
    with zipfile.ZipFile(result["archive"]) as bundle:
        assert bundle.testzip() is None
        names = bundle.namelist()
        assert any(n.endswith("queue.html") for n in names)
        assert any(n.endswith(".3mf") for n in names)
        assert any(n.endswith("SHA256SUMS") for n in names)
        assert not any("connection" in n or n.endswith(".gcode") for n in names)
    assert project.read_plan()["manifest_sha256"] == result["plan"]["manifest_sha256"]
    assert project.slice("plate_001")["reason"] == "missing_preset"


def test_tampered_source_and_plate_cannot_be_sliced(project):
    project.export()
    target = project.plan_dir() / "plate_001.3mf"
    target.write_bytes(b"modified")
    with pytest.raises(ValueError, match="files changed"):
        project.read_plan()
    project.export()
    (project.parts_dir / "stl" / "part_0.stl").write_bytes(b"modified")
    with pytest.raises(ValueError):
        project.read_plan()


def test_changed_project_gets_new_plan_and_preserves_old(project):
    old = project.export()
    project.config["layout"]["part_spacing_mm"] += 1
    assert project.plan_id() != old["plan_id"]
    with pytest.raises(ValueError, match="No plan"):
        project.read_plan()
    new = project.export()
    assert Path(old["output_dir"]).exists()
    assert new["plan_id"] != old["plan_id"]


def test_changed_yaml_is_not_silently_ignored(project):
    project.export()
    text = project.path.read_text().replace("process_clearance_mm: 8", "process_clearance_mm: 9")
    project.path.write_text(text)
    with pytest.raises(ValueError, match="configuration changed"):
        project.plan_id()
    updated = PrintProject(project.root, "project.yaml")
    assert updated.config["layout"]["process_clearance_mm"] == 9


def test_truncated_checksum_manifest_is_rejected(project):
    project.export()
    (project.plan_dir() / "SHA256SUMS").write_text("")
    with pytest.raises(ValueError, match="checksum coverage"):
        project.read_plan()


def test_omitted_layout_defaults_round_trip_through_plan(project):
    config = yaml.safe_load(project.path.read_text())
    del config["layout"]["part_spacing_mm"]
    project.path.write_text(yaml.safe_dump(config))
    project = PrintProject(project.root, "project.yaml")
    project.export()
    assert project.read_plan()["project"]["layout"]["part_spacing_mm"] == 5


def test_local_configuration_cannot_follow_parent_symlink_outside_repo(project, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (project.root / ".local").mkdir()
    (project.root / ".local/printing").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="inside the repository"):
        configure_printer(project.root, "http://192.0.2.1", url_only=True)
    assert not (outside / "connection.json").exists()


@pytest.mark.parametrize("value", ["/tmp/source", "../outside"])
def test_project_rejects_paths_outside_repository(project, value):
    with pytest.raises(ValueError):
        project.local_path(value)


def test_printer_credentials_never_appear_in_status_or_export(project, monkeypatch):
    monkeypatch.setenv("PRUSALINK_USERNAME", "fixture-user-abc")
    monkeypatch.setenv("PRUSALINK_PASSWORD", "fixture-secret-abc")
    configure_printer(project.root, "http://192.0.2.1", url_only=True)
    result = project.export()
    assert project.status()["prusalink_auth_configured"] is True
    assert "fixture-secret" not in json.dumps(project.status())
    with zipfile.ZipFile(result["archive"]) as bundle:
        assert all(b"fixture-secret" not in bundle.read(n) for n in bundle.namelist())
    assert (project.root / ".local/printing/connection.json").stat().st_mode & 0o777 == 0o600


def test_codex_config_preserves_settings_and_contains_no_credentials(project):
    python = project.root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    directory = project.root / ".codex"
    directory.mkdir()
    (directory / "config.toml").write_text('model = "existing-model"\n')
    assert configure_mcp(project.root, "project.yaml")["state"] == "configured"
    contents = (directory / "config.toml").read_text()
    parsed = tomllib.loads(contents)
    assert parsed["model"] == "existing-model"
    assert parsed["mcp_servers"]["uav_print"]["cwd"] == str(project.root)
    assert "password =" not in contents
    assert configure_mcp(project.root, "project.yaml")["state"] == "already_configured"
    assert contents == (directory / "config.toml").read_text()


@pytest.mark.parametrize("protocol_mode", ["auto", "legacy"])
def test_mcp_stdio_lists_bounded_tools_and_exports_review(project, protocol_mode):
    mcp = pytest.importorskip("mcp")
    repo = Path(__file__).resolve().parents[1]

    async def check():
        params = mcp.StdioServerParameters(
            command=sys.executable,
            args=["-m", "uavdesign.printing.mcp_server", "--root", str(project.root), "--project", "project.yaml"],
            cwd=repo,
            env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
        )
        async with mcp.Client(params, read_timeout_seconds=20, mode=protocol_mode) as client:
            listed = await client.list_tools()
            names = {t.name for t in listed.tools}
            assert names == {"project_status", "part_inventory", "plan_prints", "review_plate", "prepare_plate", "slice_plate", "printer_status"}
            inventory = await client.call_tool("part_inventory", {})
            assert not inventory.is_error
            assert len(inventory.structured_content["parts"]) == 2
            plan = await client.call_tool("plan_prints", {})
            assert not plan.is_error
            assert plan.structured_content["plate_count"] == 1
            assert Path(plan.structured_content["archive"]).is_file()
            review = await client.call_tool("review_plate", {"plate_id": "plate_001"})
            assert review.structured_content["state"] == "arranged_geometry"
            missing = await client.call_tool("prepare_plate", {"plate_id": "plate_001"})
            assert missing.structured_content["reason"] == "missing_preset"
            invalid = await client.call_tool("slice_plate", {"plate_id": "../source"})
            assert invalid.is_error
            # A running server must pick up edited project settings on its next call.
            config = yaml.safe_load(project.path.read_text())
            config["layout"]["process_clearance_mm"] = 9
            project.path.write_text(yaml.safe_dump(config))
            replanned = await client.call_tool("plan_prints", {})
            assert replanned.structured_content["plan_id"] != plan.structured_content["plan_id"]

    asyncio.run(check())
