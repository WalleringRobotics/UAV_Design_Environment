# UAV Design Environment — Claude Code Session Spec

## Context

Building a Python-based UAV design repository for a **Tarot X6 hexacopter platform** (and future variants) under the **Wallering Robotics** brand. The immediate hardware target is an 850–960mm hex carrying a modular sensor payload (LiDAR, thermal, multispectral, global shutter RGB) on a Pixhawk 6X / PX4 stack with NVIDIA Orin Nano companion compute.

The goal is a **structured, reproducible design environment** — not a one-shot calculator. Every sizing decision should be traceable, parameterised, and re-runnable as hardware choices evolve.

---

## Repository Structure to Scaffold

```
wallering-uav-design/
├── README.md
├── environment.yml               # conda env spec
├── requirements.txt              # pip fallback
├── .gitignore
│
├── mission/
│   ├── mission_definition.md     # human-readable mission requirements
│   └── mission_params.yaml       # structured parameters consumed by notebooks
│
├── sizing/
│   ├── 01_constraint_analysis.ipynb
│   ├── 02_mass_budget.ipynb
│   ├── 03_propulsion_sizing.ipynb
│   ├── 04_power_budget.ipynb
│   └── 05_endurance_estimate.ipynb
│
├── payload/
│   ├── payload_manifest.yaml     # sensor mass, power, volume per unit
│   └── 06_payload_trades.ipynb   # swap-bay configuration analysis
│
├── airframe/
│   └── airframe_params.yaml      # X6 frame geometry, motor positions, arm lengths
│
├── models/
│   ├── propulsion.py             # thrust/power model, motor+prop+ESC
│   ├── mass_model.py             # component mass rollup
│   ├── power_model.py            # multi-rail power budget
│   └── endurance.py              # Peukert-corrected battery endurance
│
└── outputs/
    └── figures/                  # auto-generated plots from notebooks
```

---

## Python Environment

### Core dependencies

```yaml
# environment.yml
name: uav-design
channels:
  - conda-forge
  - defaults
dependencies:
  - python=3.11
  - jupyter
  - jupyterlab
  - numpy
  - scipy
  - pandas
  - matplotlib
  - seaborn
  - pyyaml
  - pip
  - pip:
    - openmdao>=3.28
    - adopy          # if available, else manual install from sobester/ADRpy
    - plotly
    - ipywidgets
```

### Framework choices

| Framework | Role | Source |
|---|---|---|
| **OpenMDAO** | MDO infrastructure, gradient-based optimisation | `pip install openmdao` |
| **ADRpy** | Constraint analysis, W/S vs P/W diagrams | `pip install git+https://github.com/sobester/ADRpy` |
| **FAST-UAV** | Multirotor sizing spine (if applicable notebook modules exist) | `pip install git+https://github.com/SizingLab/FAST-UAV` |
| **NumPy/SciPy** | Low-level numerics, propulsion curve fitting | standard |
| **Plotly + ipywidgets** | Interactive trade study visualisation | standard |

---

## Notebook Specifications

### `01_constraint_analysis.ipynb`
**Purpose:** Define the design point before any hardware is fixed.

Inputs (from `mission_params.yaml`):
- Target AUW range (kg)
- Hover endurance target (min)
- Max wind speed (m/s)
- Altitude (m ASL, SE Bavaria ~500m)
- Payload mass worst-case (kg)

Outputs:
- Thrust-to-weight ratio required
- Disc loading vs endurance trade curve
- Minimum total thrust (N) at target AUW

Method: ADRpy-style constraint diagram adapted for multirotor (T/W vs disc area).

---

### `02_mass_budget.ipynb`
**Purpose:** Bottom-up mass rollup with parametric sensitivity.

Structure: component mass dictionary loaded from `airframe_params.yaml` and `payload_manifest.yaml`, summed with contingency factor.

| Component group | Source |
|---|---|
| Frame (Tarot X6) | Fixed: 2000g |
| Motors × 6 | Parametric input |
| ESCs × 6 | Parametric input |
| Props × 6 | Parametric input |
| Flight controller (Pixhawk 6X) | Fixed: ~70g |
| Companion computer (Orin Nano + carrier) | Fixed: ~350g |
| RTK (Holybro H-RTK F9P Helical) | Fixed: ~100g |
| RC receiver (ELRS) | Fixed: ~15g |
| Wiring + connectors | Estimate: 200g |
| Battery | Parametric (varied in endurance notebook) |
| Payload (active bay config) | From payload_manifest.yaml |
| **Total AUW** | Computed |

Sensitivity output: tornado chart of mass contributors.

---

### `03_propulsion_sizing.ipynb`
**Purpose:** Select motor/prop/ESC combination to meet T/W requirement at target AUW.

Inputs:
- AUW from notebook 02
- Target hover throttle % (60% is conventional design point for multirotor)
- Number of motors: 6
- Battery voltage: 6S (22.2V nominal, 25.2V full)

Computations:
- Required thrust per motor = (AUW × g × safety_factor) / 6
- Motor KV selection: KV = RPM_target / V_nominal
- Prop diameter constraint from X6 geometry (18" max)
- Shaft power estimate from motor efficiency curve
- ESC current rating with 20% headroom

Reference data to include:
- Tarot 5008/340KV datasheet curve (baseline)
- T-MOTOR MN505-S or equivalent (upgrade comparison)
- Thrust/current tables at 6S for candidate props (18×5.5, 1855 CF)

Output: recommended motor+prop+ESC triplet with operating point plot.

---

### `04_power_budget.ipynb`
**Purpose:** Multi-rail power architecture for all onboard systems.

Rails to model:

| Rail | Voltage | Consumers |
|---|---|---|
| Main (propulsion) | 6S (22.2V) | Motors + ESCs |
| Regulated 5V | 5V | RC receiver, some sensors |
| Regulated 12V | 12V | Orin Nano (via carrier board) |
| Sensor rail | 5V or 12V TBD | LiDAR, thermal, cameras |

Inputs: per-component idle and peak current draw from datasheets.
Output: total current draw at hover, max continuous current, BEC/UBEC sizing recommendation.

---

### `05_endurance_estimate.ipynb`
**Purpose:** Battery capacity → hover endurance with Peukert correction.

Model:
```
t = (C_rated × eta_peukert) / I_hover
```

Where:
- `C_rated` = battery capacity (Ah), swept parametrically (10Ah → 22Ah 6S)
- `eta_peukert` = Peukert efficiency at discharge rate C_rate
- `I_hover` = total current from notebook 04 at hover throttle

Sweep variables:
- Battery capacity (Ah)
- Payload config (light / medium / heavy from payload_manifest)
- Altitude correction factor

Output: endurance surface plot (capacity × payload config), with 20% reserve margin marked.

---

### `06_payload_trades.ipynb`
**Purpose:** Evaluate swap-bay configurations against mass and power budget.

Payload manifest structure (`payload_manifest.yaml`):

```yaml
payloads:
  stereo_cam:
    mass_g: 200
    power_w: 5
    volume_cc: 150
    interface: USB3

  orin_nano:
    mass_g: 350
    power_w: 15
    volume_cc: 400
    interface: internal
    always_on: true

  livox_mid360:
    mass_g: 265
    power_w: 9
    volume_cc: 300
    interface: ethernet

  flir_boson_plus:
    mass_g: 95
    power_w: 2.5
    volume_cc: 80
    interface: USB3

  micasense_altum_pt:
    mass_g: 410
    power_w: 8
    volume_cc: 500
    interface: ethernet

  global_shutter_rgb:
    mass_g: 150
    power_w: 4
    volume_cc: 120
    interface: USB3
```

Logic:
- `always_on` components always included in mass + power totals
- Generate all valid combinations of remaining payloads (max 2 simultaneous bays)
- Filter by: total payload mass ≤ budget, total power ≤ rail capacity
- Output: ranked table of valid configurations with endurance impact per config

---

## YAML Parameter Files to Create

### `mission_params.yaml`
```yaml
mission:
  name: "SE Bavaria agricultural survey"
  altitude_asl_m: 500
  target_hover_endurance_min: 20
  max_wind_speed_ms: 8
  operating_temp_range_c: [-5, 35]

design_point:
  target_auw_kg: 6.5
  hover_throttle_fraction: 0.60
  thrust_to_weight_ratio: 2.0
  safety_factor: 1.15
```

### `airframe_params.yaml`
```yaml
airframe:
  name: "Tarot X6 TL6X001"
  wheelbase_mm: 960
  num_motors: 6
  max_prop_diameter_in: 18
  frame_mass_g: 2000
  landing_gear_clearance_mm: 395
  arm_tube_od_mm: 25
  motor_mount_patterns_mm: [16, 19, 25]
```

---

## Immediate Tasks for Claude Code

1. Scaffold the full directory structure above
2. Create `environment.yml` and `requirements.txt`
3. Create all YAML parameter files with values above
4. Create `models/propulsion.py` with:
   - `thrust_per_motor(auw_kg, n_motors, tw_ratio)` 
   - `motor_kv_estimate(voltage, rpm_target)`
   - `prop_power_estimate(thrust_n, disc_area_m2, air_density)`
5. Create `models/mass_model.py` with component rollup class
6. Create `models/power_model.py` with multi-rail budget class
7. Create `models/endurance.py` with Peukert endurance model
8. Create notebook 01 (constraint analysis) as a working notebook with ADRpy integration
9. Create notebook 02 (mass budget) populated with Tarot X6 values and tornado chart
10. Stub notebooks 03–06 with section headers, input cells, and placeholder output cells

---

## Notes for Claude Code

- Use **metric units throughout** (SI); label all variables with units in comments
- All notebooks should be runnable top-to-bottom without errors on first execution
- Parametric inputs should come from YAML files, not hardcoded in notebooks
- Plots should save to `outputs/figures/` automatically
- Add a `README.md` that explains the design flow: mission → constraint → mass → propulsion → power → endurance → payload trades
- Git-initialise the repo with a sensible `.gitignore` (exclude `outputs/figures/`, `__pycache__`, `.ipynb_checkpoints`)
