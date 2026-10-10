"""Offline boundary checks for printer telemetry and slicer integration."""

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request
import zipfile

import pytest

from uavdesign.printing import prusalink, slicer


class Reply:
    def __init__(self, body=b"{}", status=200):
        self.body, self.status = body, status

    def read(self, size):
        return self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class Opener:
    def __init__(self, replies):
        self.replies, self.requests = iter(replies), []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_status_is_get_only_redacts_credentials_and_handles_empty_job():
    client = prusalink.PrusaLink("http://192.168.1.10", "maker", "secret-value")
    client._opener = Opener([
        Reply(b'{"firmware":"7.0.0"}'), Reply(b'{"hostname":"maker printer","api_key":"anything"}'),
        Reply(b'{"printer":{"state":"IDLE","note":"secret-value"}}'), Reply(), Reply(status=204),
    ])
    result = client.status_snapshot()
    assert result["state"] == "available"
    assert result["data"]["job"] is None and result["print_ready"] is None
    assert "secret-value" not in json.dumps(result) and "maker" not in json.dumps(result)
    assert result["data"]["info"]["api_key"] == "[redacted]"
    assert all(request.method == "GET" and timeout == 5 for request, timeout in client._opener.requests)
    assert len(client._opener.requests) == 5


def test_status_failure_remains_visible_without_auth_details():
    client = prusalink.PrusaLink("http://192.168.1.10", "maker", "secret-value")
    client._opener = Opener([
        HTTPError("http://secret-value/", 401, "secret-value", {}, None),
        URLError("secret-value"), Reply(b"<html>secret-value</html>"), Reply(b"[]"), Reply(status=204),
    ])
    result = client.status_snapshot()
    assert result["state"] == "unavailable"
    assert result["errors"]["version"] == {"kind": "http_error", "status": 401}
    assert "secret-value" not in json.dumps(result)


def test_status_partial_and_oversized_responses():
    client = prusalink.PrusaLink("https://printer.local", "maker", "secret-value")
    client._opener = Opener([Reply(), Reply(b" " * 1_048_577), Reply(), Reply(), Reply(status=204)])
    result = client.status_snapshot()
    assert result["state"] == "partial" and "info" in result["errors"]


@pytest.mark.parametrize("url", ["http://user:password@printer", "file:///etc/passwd", "http://printer/api", "http://printer?token=x", "http://printer/#secret", "http://printer:bad"])
def test_connection_rejects_credential_urls_and_non_origins(url):
    with pytest.raises(prusalink.PrusaLinkError):
        prusalink.PrusaLink(url, "maker", "secret")


def test_connection_disables_proxy_and_redirects():
    client = prusalink.PrusaLink("http://192.168.1.10", "maker", "secret")
    assert not any(getattr(handler, "proxies", None) for handler in client._opener.handlers)
    redirect = next(handler for handler in client._opener.handlers if isinstance(handler, prusalink._NoRedirects))
    with pytest.raises(prusalink.PrusaLinkError, match="redirects"):
        redirect.redirect_request(Request(client.url), None, 302, "redirect", {}, "https://evil.example")


def test_environment_missing_configuration_never_echoes_credentials(monkeypatch):
    monkeypatch.setenv("PRUSALINK_PASSWORD", "very-private")
    monkeypatch.delenv("PRUSALINK_URL", raising=False)
    with pytest.raises(prusalink.PrusaLinkError) as caught:
        prusalink.PrusaLink.from_environment()
    assert "very-private" not in str(caught.value)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    mesh = '''<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
<resources><object id="1" type="model"><mesh><vertices>
<vertex x="10" y="10" z="0"/><vertex x="20" y="10" z="0"/>
<vertex x="10" y="20" z="0"/><vertex x="10" y="10" z="10"/>
</vertices><triangles><triangle v1="0" v2="1" v3="2"/><triangle v1="0" v2="3" v3="1"/>
<triangle v1="0" v2="2" v3="3"/><triangle v1="1" v2="3" v3="2"/>
</triangles></mesh></object></resources><build><item objectid="1"/></build></model>'''
    plate = tmp_path / "plate.3mf"
    with zipfile.ZipFile(plate, "w") as archive:
        archive.writestr("3D/3dmodel.model", mesh)
    presets = tmp_path / "presets"
    presets.mkdir()
    preset = presets / "wing.ini"
    settings = {
        "printer_model": "COREONE", "printer_settings_id": "Prusa CORE One 0.4 nozzle",
        "print_settings_id": "Wing skin", "filament_settings_id": "ColorFabb LW-ASA",
        "bed_shape": "0x0,250x0,250x220,0x220", "max_print_height": "270", "nozzle_diameter": "0.4",
        "gcode_flavor": "marlin2", "filament_type": "ASA", "filament_diameter": "1.75",
        "filament_density": "1.07", "extrusion_multiplier": "0.4", "temperature": "250",
        "first_layer_temperature": "250", "bed_temperature": "100", "first_layer_bed_temperature": "100",
        "layer_height": "0.25", "first_layer_height": "0.2", "perimeters": "1", "fill_density": "7%",
        "fill_pattern": "gyroid", "extrusion_width": "0.5", "support_material": "0",
        "start_gcode": "G28", "end_gcode": "M104 S0", "post_process": "",
        "perimeter_speed": "40", "infill_speed": "50", "travel_speed": "100", "retract_length": "0.8",
    }
    preset.write_text("\n".join(f"{key} = {value}" for key, value in settings.items()))
    monkeypatch.setattr(slicer, "_probe", lambda executable: {"executable": "/fake/prusa-slicer", "version": "2.9.6", "sha256": "binaryhash"})
    return plate, preset, tmp_path / "gcode" / "plate.gcode", settings


EXPECTED = {"perimeters": 1, "extrusion_width_mm": .5, "infill_fraction": .07,
            "infill": "gyroid", "layer_height_mm": .25, "supports": "none", "material": "lw_asa"}


def test_prepare_preserves_geometry_and_records_complete_provenance(inputs):
    plate, preset, output, _ = inputs
    result = slicer.prepare_slice(plate, [preset], output, expected_settings=EXPECTED)
    assert result["state"] == "prepared" and not output.parent.exists()
    assert "--dont-arrange" in result["command"] and "--no-binary-gcode" in result["command"]
    assert result["command"][result["command"].index("--post-process") + 1] == ""
    assert len(result["plate"]["sha256"]) == 64 and len(result["preset"]["sha256"]) == 64


@pytest.mark.parametrize("key,value,error", [
    ("printer_model", "MK4", "printer_model"), ("nozzle_diameter", "0.6", "nozzle"),
    ("bed_shape", "0x0,200x0,200x200,0x200", "bed_shape"),
    ("perimeters", "3", "perimeters"), ("fill_density", "20%", "fill_density"),
    ("layer_height", "0.2", "layer_height"), ("filament_type", "PLA", "material family"),
    ("filament_settings_id", "Generic ASA", "explicitly named"),
    ("post_process", "curl evil", "post-processing"),
])
def test_incompatible_profile_is_rejected_before_executable(inputs, key, value, error):
    plate, preset, output, settings = inputs
    settings[key] = value
    preset.write_text("\n".join(f"{k} = {v}" for k, v in settings.items()))
    with pytest.raises(slicer.SlicerError, match=error):
        slicer.prepare_slice(plate, [preset], output, expected_settings=EXPECTED)


def test_incomplete_and_sectioned_presets_are_explicit(inputs):
    plate, preset, output, _ = inputs
    for text, match in [("perimeters=1", "Incomplete"), ("[printer:mine]\nperimeters=1", "sectioned")]:
        preset.write_text(text)
        with pytest.raises(slicer.SlicerError, match=match):
            slicer.prepare_slice(plate, [preset], output)


def test_embedded_project_config_is_rejected(inputs):
    plate, preset, output, _ = inputs
    with zipfile.ZipFile(plate, "a") as archive:
        archive.writestr("Metadata/Slic3r_PE.config", "post_process = command")
    with pytest.raises(slicer.SlicerError, match="embedded"):
        slicer.prepare_slice(plate, [preset], output)


def test_out_of_bed_geometry_is_rejected(inputs):
    plate, preset, output, _ = inputs
    with zipfile.ZipFile(plate) as archive:
        mesh = archive.read("3D/3dmodel.model").replace(b'x="20"', b'x="270"')
    with zipfile.ZipFile(plate, "w") as archive:
        archive.writestr("3D/3dmodel.model", mesh)
    with pytest.raises(slicer.SlicerError, match="exceeds"):
        slicer.prepare_slice(plate, [preset], output)


def _gcode_text(settings):
    header = "\n".join(f"; {key} = {settings[key]}" for key in ("printer_model", "nozzle_diameter", "bed_shape", "max_print_height"))
    return header + "\n; estimated printing time (normal mode) = 1m 2s\n; filament used [mm] = 42.5\n;LAYER_CHANGE\nM83\nG1 X10 Y10 E1\nG1 X20 Y10 E1\nG1 X20 Y20 E1\nG1 X10 Y20 E1\n"


def test_actual_slice_validates_and_publishes_new_file(inputs, monkeypatch):
    plate, preset, output, settings = inputs
    def run(command, timeout):
        Path(command[command.index("--output") + 1]).write_text(_gcode_text(settings))
        return 0, "done"
    monkeypatch.setattr(slicer, "_run", run)
    result = slicer.slice_plate(plate, [preset], output, expected_settings=EXPECTED)
    assert result["state"] == "sliced_for_review" and result["print_ready"] is None
    assert result["gcode"]["estimated_time_s"] == 62 and result["gcode"]["filament_mm"] == 42.5
    assert output.is_file()
    with pytest.raises(slicer.SlicerError, match="new .gcode"):
        slicer.slice_plate(plate, [preset], output)


@pytest.mark.parametrize("content,returncode,match", [(None, 0, "no usable"), ("; no toolpath\n" * 10, 0, "substantive"), (None, 1, "exit status")])
def test_slicer_success_exit_is_insufficient(inputs, monkeypatch, content, returncode, match):
    plate, preset, output, _ = inputs
    def run(command, timeout):
        if content:
            Path(command[command.index("--output") + 1]).write_text(content)
        return returncode, ""
    monkeypatch.setattr(slicer, "_run", run)
    with pytest.raises(slicer.SlicerError, match=match):
        slicer.slice_plate(plate, [preset], output)
    assert not output.exists() and not list(output.parent.glob(".slice-*"))


def test_changed_source_discards_gcode(inputs, monkeypatch):
    plate, preset, output, settings = inputs
    def run(command, timeout):
        Path(command[command.index("--output") + 1]).write_text(_gcode_text(settings))
        preset.write_text(preset.read_text() + "\n# changed\n")
        return 0, ""
    monkeypatch.setattr(slicer, "_run", run)
    with pytest.raises(slicer.SlicerError, match="changed"):
        slicer.slice_plate(plate, [preset], output)
    assert not output.exists()


def test_output_publishing_does_not_overwrite_raced_file(inputs, monkeypatch):
    plate, preset, output, settings = inputs
    def run(command, timeout):
        Path(command[command.index("--output") + 1]).write_text(_gcode_text(settings))
        output.write_text("existing job")
        return 0, ""
    monkeypatch.setattr(slicer, "_run", run)
    with pytest.raises(slicer.SlicerError, match="refusing to overwrite"):
        slicer.slice_plate(plate, [preset], output)
    assert output.read_text() == "existing job"


def test_binary_missing_or_unsuitable_is_explicit(monkeypatch):
    monkeypatch.setattr(slicer.shutil, "which", lambda executable: None)
    with pytest.raises(slicer.SlicerError, match="unavailable"):
        slicer._probe("missing-binary")
    monkeypatch.setattr(slicer.shutil, "which", lambda executable: "/bin/false")
    monkeypatch.setattr(slicer, "_run", lambda argv, timeout: (0, "other slicer"))
    with pytest.raises(slicer.SlicerError, match="identify"):
        slicer._probe("other-binary")


def test_binary_probe_uses_supported_help_banner_not_version_flag(tmp_path, monkeypatch):
    binary = tmp_path / "prusa-slicer"
    binary.write_bytes(b"test binary")
    monkeypatch.setattr(slicer.shutil, "which", lambda executable: str(binary))
    commands = []
    def run(argv, timeout):
        commands.append(argv)
        if argv[-1] == "--help":
            return 0, "PrusaSlicer-2.9.6+linux-x64 --load --dont-arrange --export-gcode --output --config-compatibility"
        assert argv[-1] == "--help-fff"
        return 0, "--post-process --binary-gcode"
    monkeypatch.setattr(slicer, "_run", run)
    result = slicer._probe("prusa-slicer")
    assert result["version"] == "2.9.6+linux-x64" and len(result["sha256"]) == 64
    assert len(commands) == 2


@pytest.mark.parametrize("replace_with,match", [
    (("; nozzle_diameter = 0.4", "; nozzle_diameter = 0.6"), "nozzle"),
    (("1m 2s", "0s"), "estimates"),
    (("42.5", "0"), "estimates"),
])
def test_toolpath_and_exit_success_do_not_override_bad_metadata(inputs, monkeypatch, replace_with, match):
    plate, preset, output, settings = inputs
    def run(command, timeout):
        Path(command[command.index("--output") + 1]).write_text(_gcode_text(settings).replace(*replace_with))
        return 0, ""
    monkeypatch.setattr(slicer, "_run", run)
    with pytest.raises(slicer.SlicerError, match=match):
        slicer.slice_plate(plate, [preset], output)
    assert not output.exists()
