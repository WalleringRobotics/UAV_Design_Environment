# Wallering UAV Design Environment

A reproducible Python design environment for Wallering Robotics airframes. The
repository captures every sizing decision as parameterised, re-runnable
analysis — not a one-shot calculator.

Two platforms share one set of models:

| Platform | Directory | Baseline |
|---|---|---|
| **Multirotor** | `platforms/multirotor/` | Tarot X6 hexacopter, 6.5 kg, modular sensor payload, Pixhawk 6X + Orin Nano |
| **Flying wing** | `platforms/flying_wing/` | 700 mm swept tailless wing, ~0.9 kg, pusher, hand-launched |

---

## How the pieces fit

Each platform has its own **front end** (how the airframe turns weight into
power required) and shares a common **back end** (mass, avionics power,
battery, endurance, payloads).

```
                 mission/mission_params.yaml       payload/payload_manifest.yaml
                      (site, environment)            (sensors: mass, power)
                              |                                |
            +-----------------+----------------+---------------+
            |                                  |
   platforms/multirotor/               platforms/flying_wing/
   T/W, disc loading                   W/S vs P/m matching chart
   momentum-theory hover power         MAC, neutral point, static margin
                                       drag polar, D*V / eta_prop
            |                                  |
            +----------------+-----------------+
                             |
                 electrical power per mission segment
                             |
                 uavdesign.endurance   (Peukert, reserve, mission energy)
                 uavdesign.mass        (rollup, contingency, tornado, CG)
                 uavdesign.power       (avionics + payload rails, BEC sizing)
```

The seam is **electrical power at the pack**. Once a platform reduces a flight
segment to watts, battery sizing and endurance are identical for both.

## Repository layout

```
uavdesign/              Installable package — every model lives here
  atmosphere.py           ISA density, wing-loading unit helpers
  mass.py                 Mass budget, contingency, tornado, CG + battery placement
  power.py                Avionics/payload multi-rail power budget
  endurance.py            Battery, Peukert, mission-segment energy
  propulsion.py           Rotor (hover) and propeller (cruise) power, shaft -> electrical
  aero/                   Fixed wing: planform/MAC/static margin, drag polar, constraints
mission/                Shared mission definition + site parameters
payload/                Shared payload manifest
platforms/
  multirotor/             airframe_params.yaml, design_point.yaml, notebooks 01-06
  flying_wing/            airframe_params.yaml, design_point.yaml, notebooks 01-05
scripts/build_notebooks.py   Regenerates notebooks from scripts/nbdefs/<platform>.py
tests/                  Model tests + "every notebook runs" test
outputs/figures/<platform>/  Auto-generated plots (gitignored)
docs/                   Original design environment spec
```

## Design flows

**Multirotor** (`platforms/multirotor/`)

```
01_constraint_analysis  --> required T/W, disc loading, min thrust
02_mass_budget          --> AUW, mass tornado chart
03_propulsion_sizing    --> motor / prop / ESC selection
04_power_budget         --> per-rail current, BEC sizing
05_endurance_estimate   --> Peukert-corrected endurance surface
06_payload_trades       --> swap-bay configuration ranking
```

**Flying wing** (`platforms/flying_wing/`)

```
01_constraint_analysis       --> W/S vs P/m matching chart, stall + hand-launch limits
02_geometry_and_cg           --> MAC, neutral point, target CG for the static margin
03_mass_and_balance          --> component rollup, battery placement, ballast check
04_aero_performance          --> drag polar, power-required curve, stall-limited speeds
05_propulsion_and_endurance  --> cruise power -> shared endurance model, capacity sweep
```

The wing geometry model reproduces the rcplanes.online flying-wing CG
calculator to 0.01 mm for the baseline planform; `tests/test_wing.py` locks
that in, and also checks that a multi-panel (cranked) wing composes exactly.

## Getting started

```bash
# Conda (preferred)
conda env create -f environment.yml
conda activate uav-design

# Pip fallback
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # includes `pip install -e .`

pytest                               # models + run every notebook
jupyter lab
```

Open a platform's `01_*.ipynb` and run top-to-bottom. Notebooks also work
without installing the package: their first cell finds the repo root.

## Conventions

- **Units:** SI throughout, with unit suffixes in names (`mass_kg`,
  `current_a`, `voltage_v`, `thrust_n`). Exception: wing geometry is in mm,
  matching how small planforms are drawn; flying-wing positions are measured
  aft of the wing root leading edge.
- **Parameters:** Notebooks never hardcode design inputs — edit the YAMLs.
  Shared inputs live in `mission/` and `payload/`; platform inputs in
  `platforms/<platform>/`.
- **Notebooks are generated:** edit `scripts/nbdefs/<platform>.py`, then run
  `python scripts/build_notebooks.py`.
- **Plots:** Saved to `outputs/figures/<platform>/` (gitignored).
- **Reproducibility:** Notebooks must run top-to-bottom on a fresh kernel —
  enforced by `tests/test_notebooks.py` in CI.

## Adding a platform

1. Create `platforms/<name>/` with `airframe_params.yaml` and `design_point.yaml`.
2. Write the front end (power required per flight segment) using
   `uavdesign.propulsion` / `uavdesign.aero`, adding models to the package
   rather than to notebooks.
3. Add `scripts/nbdefs/<name>.py` and register it in `scripts/build_notebooks.py`.

## Hardware baselines

**Multirotor**

| Item | Value |
|---|---|
| Frame | Tarot X6 TL6X001, 960 mm wheelbase |
| Motors | 6 × (parametric — Tarot 5008/340 KV baseline) |
| Battery | 6S Li-ion / LiPo, 10–22 Ah swept |
| Flight controller | Pixhawk 6X |
| Companion computer | NVIDIA Orin Nano |
| RTK GNSS | Holybro H-RTK F9P Helical |

**Flying wing** (component masses are placeholders until parts are weighed)

| Item | Value |
|---|---|
| Planform | Root 275 mm, tip 107 mm, half span 350 mm, LE sweep 217 mm (31.8°) |
| Wing area / AR | 13.37 dm², 3.66 |
| Static margin | 6 % MAC |
| Battery | 3S Li-ion, 5 Ah baseline, 2.5–10 Ah swept |
| Propulsion | Pusher, parametric |

Both platforms operate at ~500 m ASL (SE Bavaria). See
`docs/uav_design_env_spec.md` for the original session spec.
