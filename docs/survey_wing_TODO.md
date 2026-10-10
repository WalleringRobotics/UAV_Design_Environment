# Survey wing — remaining work (hand-off plan for a coding agent)

Branch `feature/survey-wing-fabrication` → draft PR #3, stacked on PR #2
(`feature/flying-wing-platform`). Merge #2 first, then retarget #3 to `main`.

## 0. Orientation (read first)

Pipeline: YAML → design → CAD → calibration → design (loop) → print files.

| Step | Code | Inputs |
|---|---|---|
| Payload | `uavdesign/payload.py` | `payload/survey_cage.yaml` (configs `orin`, `cm5`) |
| Survey speed limit | `uavdesign/survey.py` | `design_point.yaml: survey` |
| Polar | `uavdesign/aero/airfoil.py` (AeroSandbox + NeuralFoil) | `planform` |
| Mass closure | `uavdesign/sizing.py` | `requirements`, `structure`, `propulsion`, `battery` |
| Trim / neutral point | `uavdesign/aero/stability.py` (VLM, Panknin check) | `planform` |
| Whole chain | `uavdesign/design.py: run()`, `airframe_geometry()` | all of `platforms/survey_wing/` |
| Electronics | `uavdesign/electronics.py` | `platforms/survey_wing/electronics.yaml` |
| CAD | `uavdesign/fab/{geometry,parts,printer,massprops,build,render}.py` | `platforms/survey_wing/fabrication.yaml` |
| Loop + export | `scripts/build_parts.py` → `outputs/parts/`, writes `platforms/survey_wing/calibration.yaml` | |

Setup and checks:

```bash
pip install -e ".[cad,test]"
pytest -q -m "not cad" --ignore=tests/test_notebooks.py   # ~15 s, must stay green (50 tests)
pytest -q -m cad                                          # full CAD build, ~4 min
python scripts/build_parts.py                             # converge + export, ~10 min
python scripts/build_parts.py --no-converge               # one build from calibration.yaml, ~3.5 min
```

Last converged state (Orin config):
- **Mass and size:** 3.40 kg AUW, 2.21 m span.
- **Parts:** 35 printed parts, all fit.
- **Balance:** SM 6.8 % (target 6 %), battery at x = 40 mm (forward bay limit).

Conventions:
- **Coordinates:** x aft from the wing root leading edge, y right, z up, millimetres.
- **CAD tolerances:** use `fab.massprops` for volume and area, never `shape.Volume()`, which under-reads B-spline lofts by up to 20 %. Fuse boolean tools before a cut; a compound of overlapping tools silently destroys geometry.

---

## 1. CI for the CAD build — do first

**File:** `.github/workflows/ci.yml`

1. **Fast job.** Install `-e ".[test]"` and run `pytest -q -m "not cad"`. Keep the existing notebook-sync check.
2. **CAD job.**
   - Install `-e ".[cad,test]"`.
   - Run `python scripts/build_parts.py --no-converge`. It exits non-zero if any part does not fit.
   - Run `pytest -q -m cad`.
   - Upload `outputs/parts/` (STL, STEP, `PRINT_LIST.md`, `manifest.json`, PNGs) with `actions/upload-artifact@v4`.
3. **Notebook test.** `tests/test_notebooks.py` must run after the CAD job's build step, in the same job, because the fabrication notebook (task 3) reads `outputs/parts/manifest.json`.

**Done when:** both jobs are green on PR #3 and the artifact downloads with 35 STLs.

## 2. Re-run and commit the converged build

The last changes (three hatches, cut-away view) were built with `--no-converge` only.

1. Run `python scripts/build_parts.py`.
2. Commit the regenerated `platforms/survey_wing/calibration.yaml`.
3. Open `outputs/parts/preview_pod.png` and check that it shows the interior: cage, spar box and tray visible through the cut. If it doesn't, change the `view=` azimuth in `scripts/build_parts.py`.

**Done when:** `measured.auw_balance_g` and `auw_sizing_g` agree to within 1 %, and the four previews look right.

## 3. Survey-wing notebooks

1. Create `scripts/nbdefs/survey_wing.py` exporting `NOTEBOOKS`, modelled on `scripts/nbdefs/multirotor.py`. Use `_nb.bootstrap("survey_wing")`.
2. Register it in `scripts/build_notebooks.py`.
3. Generate the notebooks into `platforms/survey_wing/`.

Rules:
- No hard-coded design inputs; everything comes from `D.run()` or the YAMLs.
- Each notebook runs under 60 s on a fresh kernel, except 07, which reads the manifest.
- Figures go to `FIG_DIR`.

| Notebook | Content |
|---|---|
| `01_requirements_and_payload` | **Survey:** GSD, swath and footprint table. Speed limits vs exposure (blur) and vs fps, one plot. **Payload:** table for `orin`/`cm5` (mass, power, cage height). **Coverage:** ha/flight at the design point (`survey.coverage_ha`). |
| `02_airfoil_selection` | **Comparison:** NeuralFoil table at the design Re for mh45, mh60, mh49, s5010, e186, e184 (`airfoil.summarize`). **Plots:** cl–cd and cm–cl. **Justification:** why S5010 root and E186 tip. |
| `03_sizing_closure` | **Free sizing:** convergence history. **Trade:** AR 6–9 vs AUW and endurance (rebuild `SizingInputs` per AR). **Mass breakdown:** bar chart. **Selected hardware:** closure result. **Configs:** `d.evaluations` for both. **Calibration:** effect of `calibration.yaml` (run with `calibration={}` vs default). |
| `04_stability_and_trim` | **Neutral point:** VLM NP vs 25 % MAC, plus the pod shift. **Washout:** for the tip airfoil candidates; Panknin vs VLM table. **Trim:** elevon deflection vs static margin 4–10 % (`solve_elevon_trim`). **CG:** target and allowed range. |
| `05_performance` | **Power:** power-required curve with stall shading. **Matching chart:** reuse `aero/constraint.py`. **Endurance:** endurance and coverage vs pack 5S1P / 5S2P (`electronics.Pack.with_parallel`), each re-flown at its own mass. |
| `06_structures` | **Spars:** bending moment along the span vs capacity of joiner, sleeve and outer spar (`structures.root_bending_moment_n_mm`, `check_spar`). **Servos:** torque check. **Spar layout:** plot of `fab.geometry.spar_layout` on the planform, which needs no CAD. |
| `07_fabrication` | **Inputs:** read `outputs/parts/manifest.json`; if missing, print the build command and stop gracefully. **Tables:** parts (fit, footprint, mass, material) and printed mass by group vs the sizing estimate. **Images:** embed the preview PNGs. **Balance:** table and CG/NP/battery diagram. |
| `08_electronics` | **BOM:** table with provenance and `verified` flag. **Power tree:** utilisation bars per rail for both configs. **Wiring:** text or Mermaid block diagram. **Open items:** `Electronics.open_items()`. **Propulsion:** check from task 5.3. |

**Done when:** `python scripts/build_notebooks.py && git diff --exit-code` passes, and `pytest tests/test_notebooks.py` passes after a parts build.

## 4. CAD gaps (in `uavdesign/fab/parts.py` unless noted)

1. **Cage damper ledges — missing.** `build_pod` has a comment but no geometry.
   - Add two longitudinal ledges on the `pod_mid` inner walls at the cage base-plate height.
   - Give them 4 holes that line up with the cage tabs at `±(46−8)` mm from the lens axis (Ø8.4 for M3 rubber grommets).
   - **Done when:** the holes are coaxial with `build_cage` tab holes (add a test).
2. **Battery retention.** Add strap slots, or a printed tray with velcro slots, in both battery bays (`fabrication.yaml: layout.battery_bays_mm`; pack is 70 × 108 × 22 mm, cells along x).
3. **Hatch retention.** Add 6 × 2 mm magnet pockets: 4 per hatch plus matching pockets in the pod rim. Also a front tongue.
4. **Elevon horns and servo covers.** Add a horn boss on each `elevon1_*` and a printed servo-pocket cover. Pocket: `fab_wing.servo_pocket_mm`, at `servo_x_over_c`.
5. **Segment alignment.** Add 2–3 mm dowel holes, or a tongue, on spanwise segment faces and on the chordwise split faces of seg 1–2. The current bond relies only on the tubes.
6. **Motor slots** are approximated by 4 overlapping cylinders. Replace them with true slots: a `slot2D` on a YZ workplane at `firewall_x_mm`, fused before the cut.
7. **Pod build time** is ~2 min.
   - Profile `build_pod`. Known costs: stub fuse + inner cut ~18 s, plus the fused cutters.
   - Fallback 1: cut the hatches and splits from the spline body before adding detail.
   - Fallback 2: cache the body as a STEP keyed by a hash of the inputs.
8. **Wing-root stub** protrudes aft of the pod tail as a thin plate. Confirm it's intended (wing-root fairing to the TE) and that it clears the folding prop blades when folded.

Every new feature needs a test in `tests/test_fabrication.py`, and parts must still pass `check_fit`.

## 5. Design issues to resolve

1. **Balance.** SM is 6.8 % with the battery at the forward-bay limit; the target is 6 %.
   - Option a: move `layout.cage_lens_axis_x_mm` 125 → 130. Keep ≥ 5 mm between the cage rear (x + 46) and the spar-box lugs (`joiner_x − 12`).
   - Option b: accept 7 % and re-solve washout for 7 %.
   - Report both in notebook 04.
2. **Hand launch** of 3.4 kg at 11.5 m/s release. Add a `requirements.launch` option for bungee: higher release speed, plus a launch hook in the pod at the CG. Show the wing-area saving in notebook 03. This is a decision for Ryan; just present the trade.
3. **Propulsion check**, new function in `uavdesign/propulsion.py`. The current motor (Hacker A40-10L 500 KV, 246 g) may be oversized.
   - Use a simple prop model (CT/CP constants, or UIUC data if available offline) for the 13×8 on 5S at 500 KV.
   - Verify static thrust ≥ `launch_static_thrust_to_weight × W`, cruise current, and full-throttle current under the ESC rating.
   - Test the lighter Hacker options.
4. **Orin thermal.** The pod has an inlet and outlet but no duct.
   - Estimate airflow needed for 20 W at ΔT 15 K.
   - Size the inlet, and add a printed duct from the inlet to the Orin heatsink on the tray.
5. **BOM confirms** (`electronics.yaml`, `confirm:` fields). Agent: keep the fields and flag status only; Ryan makes the purchases.
   - ESC model.
   - Airspeed breakout vendor.
   - 6 V regulator part number.
   - Basler a2A5328-4gcPRO availability (Basler: not in series production).
   - Motor weight (vendor page lists 190 and 246 g).
   - aeronaut hub/spinner for a 5 mm shaft.

## 6. Docs and housekeeping

1. **`docs/survey_wing.md`.** A design-to-print guide:
   - The workflow diagram.
   - How to change payload, printer or materials.
   - Print order and the assembly sequence (spars → wing segments → elevons → fins → pod → spar box → cage on dampers → electronics).
   - CG check procedure with the real battery.
2. **`README.md`.** Remove the stale flying-wing wording in the "How the pieces fit" diagram and the hardware-baseline section. List the new modules.
3. **`environment.yml`.** Add `aerosandbox`, `neuralfoil` and `cadquery` (conda-forge has cadquery).
4. **`uavdesign/__init__.py`.** Add docstring entries for `survey`, `payload`, `sizing`, `design`, `electronics`, `structures` and `fab`. Keep `fab` out of the eager imports, because cadquery is optional.
5. **PR #3.** Mark ready for review once tasks 1–3 are done; tasks 4–6 can follow in separate PRs.

## Out of scope for the agent

Purchasing, choosing between bungee and hand launch, flight testing, and anything touching the Tekever side.
