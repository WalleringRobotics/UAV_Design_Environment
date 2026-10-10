# Wallering UAV Design Environment

A reproducible design-to-artifact pipeline for the new Wallering survey wing,
with the original Tarot X6 multirotor studies retained alongside it. Hardware
inputs, sizing, printable geometry and the mapping-software interface share
versioned YAML inputs.

The existing OAK/PX4 aircraft remains supported by
[WalleringRobotics/mapping_functionality](https://github.com/WalleringRobotics/mapping_functionality).
The new fixed wing has its own ArduPilot Plane hardware specification, with a
Basler IMX542 camera as the preferred, replaceable candidate and Orin/CM5 compute
options. See [the critical review](docs/critical_review.md) for the branch audit,
corrected assumptions and remaining evidence gaps.

## Generate the deliverables

Python 3.12 is the validated environment. CAD is optional for the model package.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[cad,test]'
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLBACKEND=Agg
python scripts/build_parts.py --review-out outputs/review
```

Open `outputs/review/index.html`, or share `outputs/review.zip`. The package contains:

- STEP assembly and individual parts; print-oriented STL files; four previews;
  print list and machine-readable part manifest.
- Electronics/payload/battery BOMs for Orin and CM5, power budgets and unresolved
  selection/verification items. Prices require quotes.
- Dedicated hardware and mapping software specifications, a versioned mapping
  handoff, a calibration template, exact input snapshots and checksums.
- Design results and launch, battery, propulsion, thermal and balance trades.

These are engineering review artifacts. Printer fit and CAD validity are checked;
physical assembly, material strength and flight performance still need evidence.
A failed convergence never replaces the committed calibration. Exports reject
stale CAD and replace prior generated directories only after completing the new
set. `--no-converge` builds from the saved calibration for repeat/CI checks;
`--config cm5 --no-converge` evaluates the lighter load on the same airframe.

## Plan the printer beds

The local print project arranges the exported parts for the Prusa CORE One+ and
produces an HTML review, a 3MF and footprint preview for every bed, and a ZIP.
The initial plan contains 42 parts on 36 beds. These are arranged models;
print times and filament consumption become available after configured slicing.

```bash
.venv/bin/python -m pip install -c requirements-lock.txt -e '.[printer]'
.venv/bin/python -m uavdesign.printing plan
.venv/bin/python -m uavdesign.printing configure-mcp
```

Open the returned output directory's `queue.html`. Reload this trusted repository
in Codex to enable the `uav_print` planning tools. See the [printer linkage guide](docs/printing.md)
for local printer authentication, the seven required PrusaSlicer profiles, and
the review-to-slicing workflow. Physical printing requires your final check;
this integration exposes no upload or print-start command.

## Iteration points

| Change | Input |
|---|---|
| Survey, launch, planform, propulsion model | `platforms/survey_wing/design_point.yaml` |
| Camera/lens/cage and compute choice | `payload/survey_cage.yaml` |
| Electronics, battery, rails | `platforms/survey_wing/electronics.yaml` |
| Printer, materials, joints, layout | `platforms/survey_wing/fabrication.yaml` |
| Mapping capture and mission contract | `integration/mapping_profile.yaml` |

Camera changes require both imaging and hardware inputs to change, followed by
new CAD, timing/intrinsic calibration and a throughput check. Generated
`calibration.yaml` records the CAD mass correction for the current geometry.

## Analysis and validation

Eight generated survey-wing notebooks cover requirements/payload, airfoil
selection, sizing, stability/trim, performance, structures, fabrication and
electronics. The six original multirotor notebooks remain under
`platforms/multirotor/`. Edit notebook sources in `scripts/nbdefs/`.

```bash
python scripts/build_notebooks.py
pytest -q -m 'not cad' --ignore=tests/test_notebooks.py
pytest -q -m cad
pytest -q tests/test_notebooks.py  # after the parts build; executes fresh kernels
```

Use the same BLAS/thread environment as the build command. CI separates fast
model checks from CAD/artifact generation and executes notebooks after the CAD
manifest exists. For a matching dependency environment, use the checked-in
Python 3.12 `requirements-lock.txt` and then `pip install --no-deps -e .`.

## Code and guides

`uavdesign` contains shared atmosphere/mass/power/endurance models, fixed-wing
geometry and aerodynamics, survey requirements, payload/electronics, sizing and
engineering checks. `uavdesign.fab` is the optional CadQuery geometry/export
layer. `uavdesign.integration` validates/seals the mapping handoff;
`uavdesign.artifacts` builds the distributable review package.

- [Design, printing and assembly guide](docs/survey_wing.md)
- [Dedicated hardware specification](docs/hardware_spec.md)
- [Mapping software specification](docs/software_spec.md)
- [Original handoff and acceptance plan](docs/survey_wing_TODO.md)

SI units are used except CAD geometry in millimetres. The aircraft CAD frame is
x aft from the root leading edge, y right, z up; it is not an autopilot body frame.
