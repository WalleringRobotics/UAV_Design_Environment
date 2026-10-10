"""Trim infeasibility must not masquerade as a converged endpoint design."""

import math

import pytest

from uavdesign.aero import stability as st
from uavdesign.aero.wing import Wing


@pytest.fixture
def wing():
    return Wing.trapezoidal(300, 150, 1000, le_sweep_deg=20)


@pytest.fixture(params=["washout", "elevon"])
def trim_problem(request, monkeypatch, wing):
    """Known linear moment law isolates bounded root semantics from VLM noise."""
    kind = request.param
    model = st.WingAeroModel("s5010", "e186", elevon=st.ElevonSpec(400, 940))

    def solve(root=0.375, bounds=(-2, 2), nonfinite_at=None):
        def analyse(_wing, aero_model, _speed, elevon_deg=0, pod=None):
            angle = aero_model.washout_deg if kind == "washout" else elevon_deg
            cm0 = angle - root
            if nonfinite_at is not None and angle == nonfinite_at:
                cm0 = math.nan
            return st.StabilityResult(.08, 0, 100, 100, cm0, 200)

        monkeypatch.setattr(st, "analyse", analyse)
        if kind == "washout":
            return st.solve_washout(wing, "s5010", "e186", .5, 0, bounds=bounds)
        # CG at the neutral point removes the known static-margin term.
        return st.solve_elevon_trim(wing, model, .5, 100, bounds=bounds)

    return solve


@pytest.mark.parametrize("root", [-3, 3])
def test_reject_trim_root_outside_allowed_angles(trim_problem, root):
    with pytest.raises(ValueError, match="not bracketed"):
        trim_problem(root=root)


@pytest.mark.parametrize("root", [-2, 2])
def test_exact_endpoint_trim_is_valid(trim_problem, root):
    angle, result = trim_problem(root=root)
    assert angle == root
    assert result.cm0 == 0


def test_bracketed_trim_returns_small_actual_moment_residual(trim_problem):
    angle, result = trim_problem()
    assert angle == pytest.approx(.375, abs=.025)
    assert abs(result.cm0) <= .025


@pytest.mark.parametrize("bounds", [(2, -2), (0, 0), (math.nan, 2), (-2, math.inf)])
def test_invalid_angle_intervals_are_rejected(trim_problem, bounds):
    with pytest.raises(ValueError, match="finite increasing angles"):
        trim_problem(bounds=bounds)


@pytest.mark.parametrize("nonfinite_at", [-2, 0])
def test_nonfinite_endpoint_or_midpoint_is_not_a_trim_solution(trim_problem, nonfinite_at):
    with pytest.raises(ValueError, match="nonfinite trim residual"):
        trim_problem(nonfinite_at=nonfinite_at)


def test_real_wing_infeasible_washout_bounds_raise(wing):
    """Real aerodynamic result reproduces the original unsafe endpoint fallback."""
    with pytest.raises(ValueError, match="not bracketed"):
        st.solve_washout(wing, "s5010", "e186", .5, .06, bounds=(10, 12))
