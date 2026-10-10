# Survey wing — remaining work (hand-off plan for a coding agent)

> Historical plan retained for traceability. The 10 October 2026 takeover
> consolidated all UAV branches in `codex/artifact-delivery` / PR #4. Current
> commands and artifacts are described in `README.md`; the critical assessment
> is in `docs/critical_review.md`. The final validation record is appended by
> the delivery session below. Do not treat inherited numeric results as current
> measurements or repeat completed work merely because it appears in this plan.

Branch `feature/survey-wing-fabrication` → draft PR #3, stacked on PR #2
(`feature/flying-wing-platform`). Merge #2 first, then retarget #3 to `main`.

## Resume here — Ubuntu handoff (2026-10-10)

**Scope authorized by Ryan:** complete the full TODO, work autonomously, and
commit regularly. This session ended at repository inspection so the actual
implementation can continue on Ryan's Ubuntu PC. The detailed requirements in
sections 0–6 below remain the acceptance criteria; the sequence here supersedes
their execution order where necessary.

### What this session actually completed

- Read the handoff and inspected source files at
  `74b6a9714c6ba601f3d2aac71d1b980c13bbd7e7`.
- Confirmed PR #3 is open and draft, targeting
  `feature/flying-wing-platform`; PR #2 is open, unmerged, and targets `main`.
  Recheck both before any PR operation.
- Confirmed there are no tracked `AGENTS.md` files at that revision. Check again
  on the Ubuntu checkout, including any parent-directory instructions.
- Found that **the CI implementation in task 1 already exists**:
  separate fast/CAD jobs, notebook-sync check, CAD build, CAD regression tests,
  notebook execution after the build in the same job, and artifact upload.
  Its results and artifact contents were **not verified** in this session.
- Inspected the design chain, CAD build/export/convergence, part builders,
  fabrication configuration, notebook generator, and tests.
- **No implementation changes, tests, CAD builds, previews, or regenerated
  calibration were completed.** This documentation handoff is the only remote
  change made by this session. The numbers below are inherited historical
  results, not new measurements.

The cloud shell could not connect to its configured proxy. A normal Git clone
failed, and dependency installation could not obtain AeroSandbox, NeuralFoil,
and the test tooling. CadQuery was present. The GitHub connector worked, so all
61 repository files were retrieved and their Git blob hashes verified. A local
snapshot repository was initialized solely for inspection; it has synthetic
history and must **not** be pushed. There is no local code patch to recover.
Use a normal clone of the existing GitHub branch on Ubuntu.

### Start on Ubuntu

For a new checkout (use the existing checkout instead if one is already present):

```bash
git clone --branch feature/survey-wing-fabrication \
  https://github.com/WalleringRobotics/UAV_Design_Environment.git
cd UAV_Design_Environment
git status --short
git log -5 --oneline
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[cad,test]"
export MPLBACKEND=Agg
python -m pytest -q -m "not cad" --ignore=tests/test_notebooks.py
python scripts/build_notebooks.py
git diff --exit-code -- platforms
```

Python 3.11 matches CI; `pyproject.toml` permits newer versions, but check CAD
wheel compatibility before choosing one. Install Ubuntu's matching venv package
if needed. Confirm the notebook `python3` kernel uses this environment; register
it with `python -m ipykernel install --sys-prefix --name python3` if necessary.
Record actual baseline results and dependency versions before editing.

Then run `python scripts/build_parts.py --no-converge` to establish baseline
geometry, manifests, fit, and previews, followed by the CAD and notebook tests.
Keep the exported baseline for comparison outside the final output directory.

### Work split and commit checkpoints

Each row is a bounded implementation chunk. Commit after its relevant checks
pass, and push the checkpoint to the existing branch. Include test results and
remaining limitations in the commit/PR record. Do not wait until the entire
project is finished to commit. Preserve unrelated local changes.

| Order | Work package | Commit/checkpoint gate |
|---|---|---|
| A | **Baseline and CI audit** (task 1). Verify the existing workflow before changing it. Keep notebook execution in the CAD job after manifest generation; preserve the fast job's notebook exclusion and the sync check. | Fast tests pass; baseline CAD build and CAD tests pass; inspect the artifact/manifest and existing notebook execution. Fix only demonstrated workflow gaps. |
| B | **Reliable convergence and current calibration** (task 2). Inspect/fix the stopping and failure criteria described below, run the full loop, inspect all four previews, and adjust the pod viewing angle if needed. | Commit regenerated calibration only from a successful build with sizing/balance agreement within 1%; record measurements and preview inspection. Add regression tests for changed convergence behavior. |
| C | **Notebook foundation and design notebooks 01–04** (task 3). Add/register `scripts/nbdefs/survey_wing.py`, generate checked-in notebooks, implement requirements/payload, airfoil selection, sizing, stability, and both balance alternatives. Add the launch input/trade from task 5.2 where notebook 03 needs it, retaining hand launch as the selected baseline. | Generated notebooks are deterministic, run on fresh kernels, and use YAML/model inputs. Commit definitions and generated notebooks together. Time each notebook, not merely each cell. |
| D | **Performance, structures, fabrication, and electronics notebooks 05–08** (task 3), plus the tested propulsion model (task 5.3) and thermal calculation needed for later CAD (task 5.4). | Execute all notebooks after a parts build; verify missing-manifest behavior for 07 separately. Show model assumptions and unresolved BOM evidence explicitly. Run model tests and notebook-sync check. |
| E | **Pod retention and motor features** (tasks 4.1–4.3 and 4.6). Add cage ledges, battery retention in both bays, hatch pockets/tongues, and true motor slots. Share geometric datums between mating features. | Focused geometry tests prove coaxial/aligned holes, matching pockets, connected valid solids, clearance, and printer fit. Commit in small feature groups. |
| F | **Wing fabrication features** (tasks 4.4–4.5). Add elevon horn bosses, servo covers, and segment alignment on spanwise and chordwise joints. | Add tests in `tests/test_fabrication.py`; validate both mirrored sides, feature placement, joint fit, and all-part printer fit. Update manifest expectations for added parts. |
| G | **Remaining integration and design issues** (tasks 4.7–4.8 and 5). Profile the pod before optimizing; investigate the root fairing and folded-prop envelope; build the Orin cooling duct; provide the optional bungee hook and launch trade without selecting bungee for Ryan. Preserve BOM confirmation fields. | Record measured build times, thermal sizing, geometric checks and limits. Exercise optional launch geometry separately. Report both balance alternatives with cage/lug clearance; do not claim folded-blade clearance without hub/blade geometry. |
| H | **Documentation and environment** (task 6). Write the design-to-print/assembly/CG guide; update README, environment dependencies, and package module descriptions while keeping CAD optional. | Documentation commands and references match the implementation; base imports work without eager CadQuery imports. Commit independently. |
| I | **Final integration and calibration**. Re-converge after all mass/geometry changes, regenerate notebooks, export a clean final output set, inspect previews, and rerun required checks. | All final gates below pass on the final revision; commit final calibration, generated notebooks, and updated status/results. Update PR title/body to the actual final scope. |

C–D complete the original tasks 1–3 milestone. Once that milestone has passed
locally **and in CI**, PR #3 can be marked ready as requested in task 6.5.
E–H may follow in separate PRs if that makes review clearer; they remain in scope.
If keeping everything on #3, retain draft status until the combined result is
verified. PR #2 must be merged before retargeting #3 to `main`; do not merge a
dependency merely to simplify the handoff. Review its state and checks first.

### Findings to resolve during implementation

1. **Convergence currently does not enforce the requested AUW gate.**
   `uavdesign/fab/build.py:converge` stops on changes to wing/pod correction
   factors, writes calibration even after exhausting iterations, and does not
   require sizing AUW and balance AUW to agree within 1%. Its first comparison
   also uses factors of 1 rather than the calibration loaded into the first
   design. Check cage-mass feedback too. A failed convergence must be explicit,
   and the saved calibration and exported design must describe a consistent,
   validated result. Define/test behavior for max-iteration exhaustion.
2. **The part count is historical.** The original 35-STL acceptance applies to
   the baseline. Servo covers, a duct, and optional launch hardware can change
   the count. Validate exact agreement between manifest entries and exported
   STL/STEP names, with no stale outputs, rather than pinning final acceptance
   to 35. Test default and optional builds separately.
3. **Notebook runtime is not currently enforced as a whole-notebook limit.**
   `tests/test_notebooks.py` currently gives nbclient 180 seconds per cell.
   Record/enforce the task's under-60-second fresh-kernel requirement for the
   survey notebooks other than 07; avoid rerunning expensive design/VLM work
   unnecessarily within a notebook.
4. **The PR description is stale.** It lists CAD CI as missing even though the
   workflow exists. Correct it when reporting verified results, and distinguish
   implementation from successful CI execution.
5. **Balance and fit need joint review.** A cage shift must preserve the stated
   5 mm clearance to the spar-box lugs and align the camera window, mast opening,
   tabs, ledges, and payload mass locations. Battery retention must accommodate
   the real pack envelope at the reported battery position in both bays.
6. **Propulsion and folding clearance have incomplete evidence.** A CT/CP model
   is an estimate, not measured thrust. State coefficients, voltage/RPM/load
   assumptions, and candidate motor data provenance. The selected motor mass,
   ESC, and folding hub remain confirmation items. Check the folded envelope
   separately from the existing deployed prop-plane clearance test.
7. **CAD cost should be measured before changing construction order or caching.**
   Profile `build_pod`; if caching is justified, key it by all relevant geometry
   inputs and validate that changed inputs invalidate the cached body.

### Final verification and handoff record

```bash
python scripts/build_parts.py
python -m pytest -q -m "not cad" --ignore=tests/test_notebooks.py
python -m pytest -q -m cad
python -m pytest -q tests/test_notebooks.py
python scripts/build_notebooks.py
git diff --exit-code -- platforms
git diff --check
```

Run the notebook-sync diff after committing intentional calibration/notebook
changes, so those expected edits do not obscure generator drift. Also exercise
the CI `--no-converge` path using the committed calibration. Before treating the
work as complete, record:

- Commit SHA, test counts/results, notebook runtimes, CI run, and artifact link.
- Sizing AUW, CAD balance AUW, percentage mismatch, span, static margin,
  battery position/bay, printed masses, and final part count.
- Visual inspection of all four previews, especially the pod interior.
- Manifest/STL/STEP agreement, all-part fit, and valid connected solids.
- Launch/balance alternatives, propulsion assumptions, thermal estimate, and
  unresolved vendor confirmations. Keep purchasing, launch selection, and
  flight testing with Ryan; nothing touching the Tekever side is in scope.

**Suggested first prompt for the Ubuntu Codex session:**

> Continue the full survey-wing TODO on feature/survey-wing-fabrication. Read the
> "Resume here — Ubuntu handoff" section in docs/survey_wing_TODO.md first, inspect
> the actual checkout, and start with work package A. Complete all packages
> autonomously, commit and push each validated chunk regularly, and keep me
> updated. Preserve the decisions reserved for Ryan. Do not assume the previous
> cloud session completed any implementation or verification.

---

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

## 1. CI for the CAD build — implemented; verify first

**Status at 2026-10-10:** the workflow below is already implemented at `74b6a97`;
CI results and artifacts still need verification. Preserve the fast job's
`--ignore=tests/test_notebooks.py` so fabrication notebook execution remains in
the CAD job after its build step.

**File:** `.github/workflows/ci.yml`

1. **Fast job.** Install `-e ".[test]"` and run `pytest -q -m "not cad" --ignore=tests/test_notebooks.py`. Keep the existing notebook-sync check.
2. **CAD job.**
   - Install `-e ".[cad,test]"`.
   - Run `python scripts/build_parts.py --no-converge`. It exits non-zero if any part does not fit.
   - Run `pytest -q -m cad`.
   - Upload `outputs/parts/` (STL, STEP, `PRINT_LIST.md`, `manifest.json`, PNGs) with `actions/upload-artifact@v4`.
3. **Notebook test.** `tests/test_notebooks.py` must run after the CAD job's build step, in the same job, because the fabrication notebook (task 3) reads `outputs/parts/manifest.json`.

**Done when:** both jobs are green on PR #3 and the artifact downloads with a
complete STL/STEP set matching the manifest (35 STLs for the historical baseline;
update the count for intentional new parts).

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
