# Printer linkage and print planning

The agent can arrange the repository's parts on CORE One+ beds, export a review
package, slice with your configured PrusaSlicer profiles, and read printer status.
The workflow is **arrange → review HTML/3MF → slice → review toolpaths and estimates
→ explicitly confirm a physical print**. No upload or print-start operation is
exposed by this integration.

The project configuration is
[`print_projects/survey_wing/project.yaml`](../print_projects/survey_wing/project.yaml).
It targets a 250 × 220 × 270 mm bed and a 0.4 mm nozzle. The inventory contains
**42 parts on 21 beds**, with **1,489 g of CAD-estimated printed parts**. Convex
footprint packing reduces the original 36-bed layout by 15 beds (42%).
That mass excludes supports, brims, purge and other process waste; it is not a
slicer filament estimate. Inspect actual supports and brims after slicing.

| Profile | Original beds | Optimized beds |
|---|---:|---:|
| Wing skin | 14 | 7 |
| Elevon | 6 | 1 |
| Fin | 2 | 2 |
| Pod shell | 5 | 5 |
| Hatch | 3 | 2 |
| Structural parts | 4 | 3 |
| Skid | 2 | 1 |
| **Total** | **36** | **21** |

The planner preserves the canonical print orientation and Z height, translating
parts and rotating them by arbitrary angles about Z. It keeps exact material and
profile groups together. Clearances remain **8 mm per part for the process,
5 mm between those reserved outlines, and 5 mm at the bed edge**: model geometry
stays at least 13 mm from the edge and 21 mm from other model geometry. Tall parts
can share compatible beds when printed layer by layer. This is an improved
validated arrangement, not a claim of a mathematically minimum bed count.

Prusa's official vendor bundle 2.5.11 identifies CORE One, One+ and One+ (Gen 2)
as `COREONE`, with this build volume. Its normal-flow and high-flow 0.4 mm nozzle
variants are separate presets; select the variant actually fitted to the printer.
[Official CORE One family profiles](https://github.com/prusa3d/PrusaSlicer-settings-prusa-fff/blob/main/PrusaResearch/2.5.11.ini)

## Generate and review a plan

Run these commands from the repository root, after generating `outputs/parts`:

```bash
.venv/bin/python -m pip install -c requirements-lock.txt -e '.[printer]'
.venv/bin/python -m uavdesign.printing status
.venv/bin/python -m uavdesign.printing plan
```

The command reports the current output directory and ZIP. Files live under
`outputs/print_projects/survey_wing_core_one/plans/<plan-id>/`; the ID reflects the
source manifest, project settings and planner implementation. The package includes
`queue.html`, `print_plan.json`, per-bed `.3mf` and `.svg` files, the project
snapshot and `SHA256SUMS`. The ZIP sits alongside that directory.

Open `queue.html` to compare beds, then open a selected 3MF in PrusaSlicer. Its
placements are already applied; keep them when importing. The SVG shows projected
geometry and reserved clearances, not toolpaths. These 3MFs deliberately contain
geometry without embedded printer or filament settings. Edit layout settings in
the project YAML and regenerate to produce a new plan. Source checksum mismatches
must be resolved by rebuilding the source export.

## Configure slicing

PrusaSlicer was not installed in the working environment at the initial linkage
check. Install the official application and set `slicer.executable` in the project
YAML to its command or executable path. The adapter reads its version from the
help banner and checks the required CLI options before slicing. Prusa's tagged
CLI definitions include configuration loading, preserved placement and G-code
export. [Official installation](https://github.com/prusa3d/PrusaSlicer),
[PrusaSlicer CLI options](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.6/src/libslic3r/PrintConfig.cpp)

The reviewed vendor bundle supplies standard ASA and PETG presets, but no LW-ASA
or ASA-CF preset. Matching materials, foaming flow and temperature calibration
remain unresolved, so the initial deliverable is the arranged review package,
without sliced toolpaths or print-time estimates. Printer start/end G-code should
come from the official machine preset; a generic ASA profile is insufficient to
establish the required LW-ASA or ASA-CF settings. PrusaSlicer 2.9.6 is distributed
for Linux through Flatpak; its official release has no standalone Linux binary.
[PrusaSlicer distributions](https://github.com/prusa3d/PrusaSlicer#download),
[2.9.6 release assets](https://github.com/prusa3d/PrusaSlicer/releases/tag/version_2.9.6)

For each row below, select the matching printer, filament and print settings in
PrusaSlicer, then use **File → Export → Export Config**. Save one complete,
sectionless INI at the listed path; a preset bundle is not accepted.
[Prusa's profile export instructions](https://help.prusa3d.com/article/how-to-import-and-export-custom-profiles-in-prusaslicer_382766)

| Profile | Material | Local exported configuration |
|---|---|---|
| Wing skin | LW-ASA | `.local/printing/presets/wing_skin.ini` |
| Elevon | LW-ASA | `.local/printing/presets/elevon.ini` |
| Fin | LW-ASA | `.local/printing/presets/fin.ini` |
| Pod shell | LW-ASA | `.local/printing/presets/pod_shell.ini` |
| Hatch | LW-ASA | `.local/printing/presets/hatch.ini` |
| Structural parts | ASA-CF | `.local/printing/presets/structural.ini` |
| Skid | PETG | `.local/printing/presets/skid.ini` |

The plate review lists its required wall count, extrusion width, layer height,
infill and supports, inherited from
[`fabrication.yaml`](../platforms/survey_wing/fabrication.yaml). Preparation checks
these against the exported configuration, as well as printer model, bed and
nozzle. Use clearly named LW-ASA and ASA-CF filament presets. Review actual flow
and temperatures for the material; foamed LW-ASA especially needs calibration.
Hardened-nozzle installation is currently unconfirmed. After physically verifying
it, set `printer.hardened_nozzle_installed: true` before preparing ASA-CF jobs.

```bash
.venv/bin/python -m uavdesign.printing prepare plate_001
.venv/bin/python -m uavdesign.printing slice plate_001
```

`prepare` validates dependencies and inputs without slicing. `slice` preserves
the arrangement and creates text G-code plus a JSON report under
`outputs/print_projects/survey_wing_core_one/slices/<plan-id>/<preset-id>/`.
The report records configuration/input hashes, executable version, actual
slicer time/material estimates and toolpath checks. Missing presets or slicer
dependencies remain explicit blockers. Existing G-code is not overwritten.
External post-processing commands and imported 3MF configuration are rejected.
Validation uses bounded snapshots of the inputs; slicing reads private staged
copies of those exact bytes. Source changes during preparation or execution
discard the output. Reports retain the original and actual staged commands.

Multi-part beds require **Complete individual objects** to be disabled in
PrusaSlicer (`complete_objects = 0`). The adapter checks this explicitly: these
layouts print all parts layer by layer and are not sequential-print layouts.
Sequential printing needs separate toolhead collision clearances and ordering.
Canonical part orientation and Z height remain fixed; bed packing rotates only
about the vertical axis. [Prusa's sequential-printing guidance](https://help.prusa3d.com/article/sequential-printing_124589)

Review support regions, adhesion, nozzle/material selection, the loaded spool and
the clear bed before authorizing a print. The successful slice state is
`sliced_for_review`. After your confirmation, a reviewed job can be transferred
through PrusaSlicer/Prusa Connect's interface; this repository does not automate
that action. [Prusa network-printing workflow](https://help.prusa3d.com/article/sending-g-codes-to-printer-via-network-prusa-connect-prusalink-octoprint_196761)

## Connect read-only printer status

The local address `http://192.168.178.151` is saved in the ignored
`.local/printing/connection.json`. The initial check on 2026-10-10 reached
`/api/version` and received HTTP 401 with a Digest authentication challenge.
That establishes reachability, not authenticated access or printer readiness.

Enter credentials in a local terminal using the hidden password prompt:

```bash
.venv/bin/python -m uavdesign.printing configure-printer --url http://192.168.178.151
.venv/bin/python -m uavdesign.printing printer-status
```

Do not paste the password into chat. The local connection file is written with
owner-only permissions and is excluded from Git and review exports. Environment
variables `PRUSALINK_URL`, `PRUSALINK_USERNAME` and `PRUSALINK_PASSWORD` can override
it. The status adapter performs only bounded GET requests for capabilities,
information, status, storage and the current job. It rejects redirects, bypasses
environment proxies and redacts authentication data. These routes and Digest
authentication are described in the
[official PrusaLink specification](https://github.com/prusa3d/Prusa-Link-Web/blob/master/spec/openapi.yaml).

## Enable the agent tools

```bash
.venv/bin/python -m uavdesign.printing configure-mcp
```

This registers `uav_print` in the repository's `.codex/config.toml`, preserving
unrelated configuration. Reload the trusted repository in Codex, then inspect
connected servers with `/mcp`. Codex loads project-scoped MCP configuration only
for trusted projects, and local STDIO servers run as subprocesses.
[Official OpenAI MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

The `printer` extra requires MCP Python SDK `>=2.3,<3`; the dependency lock uses
2.3.0. The server uses the v2 `MCPServer` API and communicates over local STDIO.
It exposes seven tools:

| Tool | Result |
|---|---|
| `project_status` | Dependency, profile and connection availability |
| `part_inventory` | Verified parts and their print requirements |
| `plan_prints` | Arranged beds and the review package |
| `review_plate` | A selected bed's placement details and files |
| `prepare_plate` | Validated slicer command and input provenance |
| `slice_plate` | G-code and generated slicer estimates for review |
| `printer_status` | Read-only PrusaLink snapshot |

For example: “Replan the survey-wing beds and show me the structural plate before
slicing.” Tool registration does not automatically enable access in an already
running client session; reload it after configuration.

## Where Printables fits

Printables is optional: the survey wing already supplies its own models. Prusa
documents model/project downloads and “Open in PrusaSlicer,” including an embedded
Printables tab. If a future fixture or accessory comes from Printables, preserve
its source URL, author, license and file checksum, then inspect and re-slice it
for this machine. The current planner accepts the repository's validated part
manifest; it does not scrape Printables or rely on an undocumented search API.
[Printables model import](https://help.prusa3d.com/article/opening-models-in-prusaslicer-from-supported-websites_399198),
[Printables in PrusaSlicer](https://help.prusa3d.com/article/printables-in-prusaslicer_822448)
