# Independent design review protocol

Review this repository as a reproducible engineering proposal. The requested
output is a prioritized, evidence-linked critique that another engineer or
agent can reproduce. Review the underlying design and its uncertainty as well
as whether the Python runs. A successful test run cannot establish physical
strength, image accuracy, print quality, or flight performance.

The scope is the new survey wing and its design/print/mapping handoff. Existing
OAK/PX4 multirotor studies are context, not evidence that the Basler/ArduPilot
wing is implemented or qualified. The mapping repository is a separate codebase;
capability statements here are tied to the inspected hashes in
[mapping_profile.yaml](../integration/mapping_profile.yaml).

## Entry points and supplied evidence

Start at `outputs/design_review/index.html`, or extract `outputs/design_review.zip`
and open its `index.html`. The package provides readable documentation, executed
`.ipynb` notebooks and HTML, technical pictures, the source/input snapshot,
machine-readable results, and SHA-256 checksums. The generated review index is
the authoritative file inventory for that package.

Read in this order:

1. [design_dossier.md](design_dossier.md), especially unmet requirements and the
   requirement-to-evidence table. Record the design configuration and scope.
2. Package provenance and checksums, then `outputs/review/design_summary.json`,
   `outputs/parts/manifest.json`, and `outputs/review/release_manifest.json` in
   the repository-shaped snapshot. Identify which outputs were freshly executed
   and which were imported from a validated prior export. Record any mismatch.
3. Executed notebook HTML for requirements, sizing, trim, performance, structure,
   fabrication and electronics. Use the `.ipynb` files to inspect or rerun cells.
4. Dimensioned/technical figures and the CAD isometric/top/exploded/pod views.
   Open `outputs/review/mechanical/assembly.step` for independent measurement.
   Individual STEP is aircraft-frame; STL and 3MF are print-frame.
5. BOM CSVs, rail JSON, `electronics/open_items.txt`, and
   [hardware_spec.md](hardware_spec.md). Vendor-source flags are provenance, not
   your own fresh hardware validation.
6. [software_spec.md](software_spec.md), handoff schema and validation blockers.
   Distinguish a valid interface document from an implemented/qualified adapter.
7. Print project's `queue.html`, `print_plan.json`, individual 3MFs, and
   [printing.md](printing.md). The current export is arranged geometry, unsliced.

The package is designed for offline reading. Execution requires the documented
Python environment and dependencies. Credentials and printer-local settings
are not required to assess the design and must not appear in a shared review.
Do not infer a missing file's contents from a screenshot or a previous revision.

## Identity and integrity before calculation

Keep the received archive unchanged and work in a separate extraction/copy.
Record the archive SHA-256 if an archive was supplied, the full source revision,
whether the source snapshot contains uncommitted changes, dependency versions,
operating system and Python version. A commit ID alone does not identify dirty
working-tree content; the packaged file hashes do.

From the extracted package root, check the supplied digest inventory:

```bash
sha256sum -c SHA256SUMS
```

From a repository checkout, record the source identity without changing it:

```bash
git rev-parse HEAD
git status --short
python3 --version
```

Some tools omit export timestamps or use numeric tolerances; byte-for-byte output
identity is not the sole acceptance criterion for a rebuilt STEP/notebook.
Compare source/input identity, dimensions, part names/count, model values,
residuals, and declared tolerances. A failed hash check on *the supplied sealed
artifact* remains an integrity finding and should not be explained away by CAD
floating-point differences.

## Reproduce the analysis

Run commands from a full checkout or the package's repository-shaped source
snapshot. Use a disposable copy if rerunning convergence: that command can update
`platforms/survey_wing/calibration.yaml` and generated outputs.

For an extracted review package, first run `cd source`. Documentation remains
under `source/docs/`, so its relative source and artifact links also work there.
The package root's `review_manifest.json`, `notebooks/execution_report.json`, and
`figures/` belong to the review wrapper; commands below run from its `source/`
directory or from an ordinary repository checkout.

The validated environment is Python 3.12. Install the checked-in version set,
then install this package without resolving different dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps -e .
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export MPLBACKEND=Agg
export MPLCONFIGDIR=/tmp/uav-review-matplotlib
python -m pip check
```

First run the model and interface checks:

```bash
python -m pytest -q -m 'not cad' --ignore=tests/test_notebooks.py
```

Reproduce geometry using the supplied calibration before making changes. This
allows the review to compare equivalent assumptions:

```bash
python scripts/build_parts.py --no-converge --review-out outputs/review
python -m pytest -q -m cad
python -m uavdesign.printing plan
```

Generate notebook source from its maintained definitions, then use the
design-review builder to execute the survey-wing notebooks in fresh kernels and
retain the executed files, HTML and execution report in a new review package:

```bash
python scripts/build_notebooks.py
python scripts/build_design_review.py --out outputs/design_review
```

Alternatively, `python -m pytest -q tests/test_notebooks.py` validates every
platform notebook, including the retained multirotor studies, without retaining
a full HTML review package. Do not substitute an aggregate success count for a
statement about which survey-wing notebooks were executed. A notebook marked
unavailable/skipped is missing evidence for that run; a rendered prior notebook
is not evidence of successful re-execution. The review builder's manifest
provides its precise scope.

For a deliberate new closure study, use a separate copy and run:

```bash
python scripts/build_parts.py --review-out outputs/review
```

Compare the saved calibration and convergence history before/after. The factors
and sizing/CAD mass error must all satisfy the configured convergence criteria.
An empty history after `--no-converge` means no iterative closure was run in that
invocation. A solver failing to bracket a trim root is an infeasible/unsupported
case to investigate, not permission to accept the closest endpoint as a root.

## Independent cross-checks

Use elementary calculations to challenge the exported results instead of only
calling the same implementation. These baseline relations have explicit units:

```python
import json
from pathlib import Path

report = json.loads(Path("outputs/review/design_summary.json").read_text())
s = report["selected"]
b = report["balance"]
g = report["geometry"]

assert abs(s["span_m"]**2 / s["wing_area_m2"] - 8.0) < 1e-8
sm = (b["x_np_mm"] - b["cg_x_mm"]) / g["mac_mm"]
assert abs(sm - b["static_margin"]) < 1e-10
mass_difference = abs(b["auw_g"] - 1000*s["auw_kg"]) / (1000*s["auw_kg"])
assert mass_difference < 0.01

gsd_m_px = 100.0 * (2.74e-6 / 0.025)
blur_limit_m_s = 0.6 * gsd_m_px / 0.0004
raw_bytes_s = 5320 * 3032 * 1 * 4
print({"gsd_m_px": gsd_m_px, "blur_limit_m_s": blur_limit_m_s,
       "raw_bytes_s": raw_bytes_s, "actual_static_margin": sm,
       "mass_difference_fraction": mass_difference})
```

These expected baseline results are 0.01096 m/px, 16.44 m/s, 64,520,960 bytes/s,
9.3737% static margin, and approximately 0.0684% mass difference. The literal
camera/mission values in this cross-check deliberately make assumptions visible;
update them from the reviewed input snapshot for a different configuration.

For mechanical review, independently measure bounding boxes and feature
locations from STEP; inspect thickness and connectivity; compare manifested
names and quantities against the export. For printer review, check actual 3MF
vertices against the named source STLs after rigid XY rotation/translation,
grounding and Z-height, complete part coverage, profile compatibility, bed
boundary, and true polygon separation. Overlapping AABBs do not prove collision;
disjoint convex hulls prove projected separation but leave cavities unavailable
to the current planner. A reduced bed count is not evidence of printable support
geometry or a globally optimal packing.

## Questions the review must answer

| Area | Required review question | Evidence needed to close it |
|---|---|---|
| Requirements | Which actual mission must the 50-minute requirement cover? Does it include climb/transit/turns/return? | Explicit mission allocation and accepted reserve model; Orin's present prediction is below 50 min |
| Launch | Does hand release remain reasonable for 3.67 kg at the boundary of the selected speed constraint? | Measured thrust/current at relevant pack states, launch-speed/load evidence and revised model if needed |
| Balance/control | Can attainable CG be trimmed with sufficient control travel across the intended loading/speed range? | Attainable-layout analysis and trim results; then measured mass/CG and linkage/controls evidence |
| Wind/imaging | Which line directions, winds, shutter times and altitudes meet both stall and blur constraints? | Wind-aware feasible operating region; rejection of infeasible combinations |
| Structure | Does the full load path transfer bending/torsion through printed skin, joints, sleeves and pod? | Material/process data and joint/assembly analyses or test evidence; tube bending alone is insufficient |
| CAD/assembly | Do real parts, cables, plugs, fasteners and tools fit; do hatches and battery retain under loads? | Vendor drawings and measured interfaces, section/clearance checks and assembly evidence |
| Print process | Do thin walls and foamed material meet shape, mass, adhesion and strength needs? | Calibrated machine/material profile, coupon measurements, sliced supports and representative part measurements |
| Power/thermal | Are rail peaks, minimum pack regulation and temperatures acceptable at ground idle and in flight? | Final SKUs/carriers, harness/interface drawing, current/transient and thermal-soak records |
| Capture/timing | Are every image and exposure event traceable to valid clocks without loss? | Real full-duration dataset with camera counters/events/PPK records, latency/jitter measurements and calibrated rig |
| Mapping products | Is any accuracy claim supported independently of nominal GSD? | Calibrated images, datum/reference/control definition, independent held-out checkpoints and product provenance |
| Software scope | What is implemented in the inspected mapping revision and what remains a request? | Code/tests at named revisions, adapter replay tests, Plane SITL/saved-plan evidence |

Assign uncertainty to the relevant model, source field, or missing measurement.
Avoid a single generic “more testing needed” finding when the package identifies
the exact unresolved quantity. Conversely, do not call a predicted value a
measurement because a manifest key is named `measured` or `verified`.

## Report findings in a stable format

Return a short narrative and a JSON document validated by
[review_findings.schema.json](review_findings.schema.json). Each finding needs a
stable ID, severity, status, affected requirement(s), evidence locations,
reproduction steps with expected/observed results, impact, recommended action,
and a closure criterion. Reference file plus JSON pointer, notebook cell index,
symbol/line, or figure caption as appropriate. Use hashes/revision from the
reviewed package; do not invent identity fields.

Severity convention:

- `critical`: invalidates a central result or could cause a serious failure if
  acted on; resolve before the affected downstream decision.
- `high`: unmet material requirement, incorrect engineering conclusion, or a
  missing controlling interface/evidence item.
- `medium`: bounded uncertainty or defect needing closure for a particular stage.
- `low`: limited reproducibility, documentation, or usability issue.
- `info`: an observation, question, or useful independent confirmation.

Use `open` for a new suspected issue, `confirmed` when supported/reproduced,
`resolved` only with identified closure evidence, `rejected` with the reason,
or `deferred` with the explicit future stage and impact. Keep model evidence and
physical evidence distinct. For example, this abbreviated but schema-valid
finding records the already disclosed CG shortfall:

```json
{
  "schema_version": "1.0",
  "reviewer": "independent reviewer",
  "reviewed_at": "2026-10-10",
  "source_revision": null,
  "bundle_sha256": null,
  "scope": ["survey_wing", "balance"],
  "summary": "Example format only; replace with actual review and identity.",
  "findings": [
    {
      "id": "REV-CG-001",
      "title": "Battery placement cannot meet the requested static margin",
      "severity": "high",
      "status": "confirmed",
      "category": "requirement_shortfall",
      "requirement_ids": ["RQ-04"],
      "evidence": [
        {
          "path": "outputs/review/design_summary.json",
          "locator": "/balance/target_cg_reachable",
          "kind": "calculated",
          "observation": "false; actual margin is 0.093737 versus target 0.06"
        }
      ],
      "reproduction": {
        "commands": ["python scripts/build_parts.py --no-converge --review-out outputs/review"],
        "preconditions": ["Use the reviewed baseline inputs and saved calibration"],
        "expected": "A reachable battery position supports the 6% target static margin",
        "observed": "Required battery x=124.632 mm is outside permitted intervals; selected x=35 mm",
        "tolerance": "Reported values rounded to 0.001 mm; target reachability is boolean"
      },
      "impact": "The trim design point does not match the achievable installed CG.",
      "recommended_action": "Review attainable-CG trim and revise layout or requirement with supporting analysis.",
      "closure_criteria": ["Updated layout achieves its accepted target", "Trim/control-authority analysis uses the attained CG"],
      "uncertainties": ["Physical mass and CG have not been measured"],
      "resolution_evidence": []
    }
  ]
}
```

Validate a completed report from the repository root:

```bash
python - <<'PY'
import json
from pathlib import Path
from jsonschema import Draft202012Validator
schema = json.loads(Path("docs/review_findings.schema.json").read_text())
report = json.loads(Path("review_findings.json").read_text())
Draft202012Validator(schema).validate(report)
print("Review finding structure is valid")
PY
```

A valid report structure does not establish that a finding is correct. Give an
independent calculation or reproducible observation for each substantive claim,
identify unavailable checks, and end with the decisions that the evidence can
support at this revision. Physical printing still requires the user's final
check; executing this review protocol neither sends a print nor authorizes one.
