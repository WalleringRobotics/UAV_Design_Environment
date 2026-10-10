"""Failure semantics of expensive CAD calibration, with controlled design iterates."""
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("cadquery")
from uavdesign.fab import build as B
pytestmark = pytest.mark.cad


def setup_loop(monkeypatch, tmp_path, correction=1.0, mass_error=0.0):
    used = {"wing_mass_factor": 1.4, "pod_mass_factor": 0.8, "cage_structure_g": 100.0}
    path = tmp_path / "calibration.yaml"
    path.write_text("original calibration\n")
    def design(platform, calibration=None):
        return NS(calibration=calibration or used, platform_dir=tmp_path,
                  design={"payload": {"size_for": "orin"}},
                  payloads={"orin": NS(cage_structure_mass_g=100)},
                  selected=NS(auw_kg=3.0, span_m=2.2))
    def build(platform, config, design, progress):
        return NS(design=design, balance=NS(auw_g=3000*(1+mass_error)))
    def factors(r):
        return {"wing_mass_factor": r.design.calibration["wing_mass_factor"]*correction,
                "pod_mass_factor": r.design.calibration["pod_mass_factor"],
                "cage_structure_g": r.design.calibration["cage_structure_g"],
                "measured": {"auw_balance_g": r.balance.auw_g, "auw_sizing_g": 3000}}
    monkeypatch.setattr(B.D, "run", design)
    monkeypatch.setattr(B, "build", build)
    monkeypatch.setattr(B, "calibration_from", factors)
    monkeypatch.setattr(B, "validate_build", lambda r: None)
    return path, used


def test_success_saves_used_calibration_not_unbuilt_proposal(monkeypatch, tmp_path):
    import yaml
    path, used = setup_loop(monkeypatch, tmp_path, correction=1.005)
    result, history = B.converge(max_iter=1)
    saved = yaml.safe_load(path.read_text())
    assert saved["wing_mass_factor"] == used["wing_mass_factor"]
    assert saved == result.design.calibration
    assert len(history) == 1


@pytest.mark.parametrize("correction,mass_error", [(1.1, 0), (1, 0.03)])
def test_exhaustion_preserves_previous_calibration(monkeypatch, tmp_path, correction, mass_error):
    path, _ = setup_loop(monkeypatch, tmp_path, correction, mass_error)
    with pytest.raises(B.ConvergenceError) as exc:
        B.converge(max_iter=2)
    assert len(exc.value.history) == 2
    assert path.read_text() == "original calibration\n"


def test_wrong_payload_cannot_recalibrate_shared_airframe(monkeypatch, tmp_path):
    path, _ = setup_loop(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="size_for"):
        B.converge(config="cm5")
    assert path.read_text() == "original calibration\n"
