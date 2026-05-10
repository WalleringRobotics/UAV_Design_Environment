# Wallering UAV Design Environment

A reproducible Python design environment for the **Tarot X6 hexacopter** platform
(and future Wallering Robotics multirotor variants). The repository captures every
sizing decision as parameterised, re-runnable analysis — not a one-shot calculator.

The immediate target is an 850–960 mm hex carrying a modular sensor payload
(LiDAR, thermal, multispectral, global shutter RGB) on a Pixhawk 6X / PX4 stack
with an NVIDIA Orin Nano companion computer.

---

## Design flow

The notebooks under `sizing/` and `payload/` are intended to be executed in order.
Each consumes parameters from YAML files and the upstream notebook's outputs:

```
mission/mission_params.yaml
        |
        v
01_constraint_analysis  --> required T/W, disc loading, min thrust
        |
        v
02_mass_budget          --> AUW, mass tornado chart
        |
        v
03_propulsion_sizing    --> motor / prop / ESC selection
        |
        v
04_power_budget         --> per-rail current, BEC sizing, hover I
        |
        v
05_endurance_estimate   --> Peukert-corrected endurance surface
        |
        v
06_payload_trades       --> swap-bay configuration ranking
```

## Repository layout

```
mission/   Mission definition (markdown) + structured YAML params
sizing/    Notebooks 01-05: constraint, mass, propulsion, power, endurance
payload/   Payload manifest + swap-bay trade study notebook
airframe/  Frame geometry parameters (Tarot X6 by default)
models/    Reusable Python: propulsion, mass, power, endurance models
outputs/   Auto-generated figures (gitignored)
docs/      Original design environment spec
```

## Getting started

```bash
# Conda (preferred)
conda env create -f environment.yml
conda activate uav-design

# Pip fallback
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

jupyter lab
```

Open `sizing/01_constraint_analysis.ipynb` and run top-to-bottom. All notebooks
read parameters from the YAML files under `mission/`, `airframe/`, and
`payload/`, so changing a hardware choice is a single-file edit.

## Conventions

- **Units:** SI throughout. Variables carry unit suffixes in code
  (`mass_kg`, `current_a`, `voltage_v`, `thrust_n`).
- **Parameters:** Notebooks never hardcode design inputs — edit the YAMLs.
- **Plots:** Saved automatically to `outputs/figures/` (gitignored).
- **Reproducibility:** Notebooks must run top-to-bottom on a fresh kernel.

## Hardware baseline

| Item | Value |
|---|---|
| Frame | Tarot X6 TL6X001, 960 mm wheelbase |
| Motors | 6 × (parametric — Tarot 5008/340 KV baseline) |
| Battery | 6S Li-ion / LiPo, 10–22 Ah swept |
| Flight controller | Pixhawk 6X |
| Companion computer | NVIDIA Orin Nano |
| RTK GNSS | Holybro H-RTK F9P Helical |
| Operating altitude | ~500 m ASL (SE Bavaria) |

See `docs/uav_design_env_spec.md` for the full session spec.
