# Survey wing design dossier

This dossier explains the new fixed-wing design, the calculations behind it, and
the evidence an independent reviewer needs to challenge it. It describes the
current engineering model: a roughly 2.3 m printed survey wing with a rigid
camera/GNSS payload, a 5S battery, and alternative Orin and CM5 computers. The
existing OAK/PX4 multirotor is a separate platform. The fixed wing uses an
ArduPilot Plane hardware proposal and a preferred, replaceable Basler camera.

The central unresolved results are concrete: the Orin prediction falls short of
50 minutes, the installed battery cannot achieve the 6% target static margin,
and the stated 8 m/s wind envelope is incompatible with imaging on a downwind
line at the selected cruise speed. The model also predicts insufficient static
launch thrust at nominal and minimum pack voltage. Documentation and valid CAD
make those results reviewable; they do not close them.

The numbers below are a documented baseline, rounded from
[design_summary.json](../outputs/review/design_summary.json),
[the CAD manifest](../outputs/parts/manifest.json), and
[the mapping handoff](../outputs/review/software/mapping_handoff.json).
Use the generated review package's provenance and input hashes to identify the
precise revision you are reviewing. Rebuild after changing a source input; do
not combine numbers from different exports. The independent review procedure is
in [external_review.md](external_review.md).

## What to open

Open `outputs/design_review/index.html` after running
`python scripts/build_design_review.py --out outputs/design_review`. That package
collects this dossier, executed notebooks and HTML views, design pictures,
machine-readable results, a source snapshot, and checksums. It is the shareable
entry point. The underlying engineering package remains
[outputs/review/index.html](../outputs/review/index.html).

For mechanical inspection, use these views together. They are renders of
generated CAD, not photographs of a built aircraft. Bought-in equipment is not
represented by vendor-accurate solids in the printed-parts STEP assembly.

![Printed aircraft, isometric view](../outputs/review/mechanical/preview_iso.png)

*Printed assembly: wing skins, elevons, fins, pod, and printed internal parts.
View the STEP assembly for dimensions and hidden faces.*

![Printed aircraft, top view](../outputs/review/mechanical/preview_top.png)

*Top view: sweep, segmentation, and control-surface placement. CAD coordinates
are x aft, y right, z up; the view orientation is not an autopilot convention.*

![Exploded printed assembly](../outputs/review/mechanical/preview_exploded.png)

*Exploded view: identifies separate printable pieces. The exploded offsets are
for illustration and do not define assembly clearances or installation order.*

![Pod cutaway](../outputs/review/mechanical/preview_pod.png)

*Pod cutaway: cage, spar box, and avionics support. Connector keep-outs, wiring
service loops, and final heatsink interfaces still require detailed inspection.*

## Requirements and design boundary

The mission input describes agricultural surveying around 500 m ASL, wind up to
8 m/s, and an operating-temperature request of −5 to 35 °C. The survey design
uses 100 m AGL, 80% forward overlap, 70% side overlap, a 0.4 ms exposure, and a
0.6 px motion-blur ceiling. It sizes at the configured hot-day atmosphere;
performance at the temperature extremes is not independently qualified.
[Mission inputs](../mission/mission_params.yaml),
[design inputs](../platforms/survey_wing/design_point.yaml).

The selected launch method is hand release at 11.5 m/s, with release speed at
least 1.10 times stall speed and a static-thrust target of 0.60 times weight.
Belly landing is the design intent. The endurance requirement is 50 minutes for
the heavier Orin configuration. Structure screening uses limit load factor 4.0
and safety factor 1.5. Those are analysis inputs, not a demonstrated operating
envelope. Geofence, flight site, reference station, survey accuracy targets, and
firmware revision remain unset in
[mapping_profile.yaml](../integration/mapping_profile.yaml).

The same geometry and 5S1P pack serve both compute options. The lighter payload
is evaluated on the Orin-sized wing. Changing the computer does not select a
second, smaller wing. A changed camera, pack, launch method, material, or
propulsion installation must rerun the coupled checks.

### Requirement-to-evidence map

`PASS` means the stated numerical/software check passes under its assumptions.
`UNMET` means the baseline model does not meet the stated target. `UNVERIFIED`
means the relevant evidence is absent. None of these statuses independently
authorizes fabrication, purchase, printing, or flight.

| ID / requirement | Authoritative input | Code / notebook | Result evidence | Baseline status |
|---|---|---|---|---|
| RQ-01: 50 min with Orin | `design_point.yaml: requirements.endurance_min` | `sizing.py`, notebook 05 | `design_summary.json: evaluations.orin.endurance_min = 49.4402` | **UNMET**, before allocating a complete operational mission |
| RQ-02: hand launch at 11.5 m/s with 1.10 stall margin | `requirements.hand_launch_speed_m_s`, `launch_margin` | `sizing.py`, notebooks 03/05 | Orin stall 10.4546 m/s; required release 11.5001 m/s | **UNVERIFIED** physically; numerical solution is at the boundary, with a small rounding/tolerance overshoot |
| RQ-03: static thrust ≥0.60 weight | `requirements.launch_static_thrust_to_weight`, `propulsion.screening` | `propulsion.py`, notebook 08 | `propulsion_screening.checks`: baseline 14.50/20.88/28.42 N at 15/18/21 V; required 21.57 N | **UNMET** at minimum/nominal voltage; modeled pass at full voltage, bench evidence absent |
| RQ-04: 6% static margin | `planform.static_margin`, `fabrication.yaml: layout.battery_placements` | `aero/stability.py`, `fab/build.py`, notebooks 04/07 | `balance.static_margin = 0.093737`; `target_cg_reachable = false` | **UNMET**; attainable battery location differs from trim design point |
| RQ-05: camera blur/overlap at selected 100 m AGL | `survey` in `design_point.yaml` | `survey.py`, notebook 01 | 10.96 mm/px GSD, 16.44 m/s blur limit; calm-air cruise 13.59 m/s | **PASS** for nominal pinhole/flat-ground geometry; image quality unverified |
| RQ-06: image within configured 8 m/s wind envelope | `mission_params.yaml: mission.max_wind_speed_ms` | `design.survey_wind_report`, notebook 05/engineering report | `survey_wind`: downwind 21.59 m/s >16.44 m/s | **UNMET** for this worst-case line direction/exposure |
| RQ-07: 4g limit ×1.5 safety factor | `requirements`, `structure.spars` | `structures.py`, notebook 06 | Tube bending calculation by station with declared allowable | **UNVERIFIED** as an assembled structure; joints/skins/buckling/fatigue are outside this screen |
| RQ-08: all printed geometry fits CORE One+ | `fabrication.yaml: printer`, print project | `fab/printer.py`, `printing/planner.py`, notebook 07 | 42 `parts[].fits = true`; 21 arranged beds | **PASS** geometry checks; support/brim/process qualification absent |
| RQ-09: CAD/sizing mass agreement <1% | saved `calibration.yaml` | `fab/build.py: converge`, notebook 03/07 | sizing 3665.72 g, CAD balance 3668.22 g; difference 0.0684% | **PASS** internal model consistency; actual mass unmeasured |
| RQ-10: power loads remain inside modeled rail ratings | `electronics.yaml`, `survey_cage.yaml` | `electronics.py`, notebook 08 | `power_budget.json`, `peak_power_budget.json`; servo assumed peak 2.0/2.5 A | **PASS** entered loads; inrush, stall, ripple, and temperature unverified |
| RQ-11: 4 Hz camera ingestion without losses | `mapping_profile.yaml: capture` | `integration.py`, notebook 01/08 | 64.52 MB/s raw; capacity ≥244.19 GiB and sustained write ≥83.88 MB/s requested | **UNVERIFIED**; drive results null and adapter proposed |
| RQ-12: exposure/georeferencing and fixed-wing mission contract | `mapping_profile.yaml: navigation`, `mission` | `integration.py`, handoff schema; mapping SW-01…08 | `software/validation.json: survey_ready = false` | **UNVERIFIED**, unsupported adapters and unmeasured calibration listed explicitly |
| RQ-13: user reviews final print setup before physical printing | `project.yaml: workflow` | local printing CLI/MCP, `docs/printing.md` | layout export and read-only printer status; no upload/start tool | **PASS** software boundary; no physical print is represented by this package |

Paths in the table are relative to `platforms/survey_wing/`, `uavdesign/`, or the
generated `outputs/review/` tree as appropriate. Each notebook below links the
specific shared implementation it exercises.

## Geometry, mass, and physical layout

| Quantity | Current design value | Meaning |
|---|---:|---|
| Aerodynamic span | 2289.51 mm | Mathematical wing planform, excluding extra fin/skin extents |
| Printed CAD envelope | approximately 2301 ×831 ×302 mm | Overall width ×length ×height of printed geometry; excludes propulsion hardware |
| Wing reference area | 0.65523 m² | Planform reference used by performance model |
| Aspect ratio / taper / LE sweep | 8.0 /0.50 /20° | Baseline choices; AR comparison in notebook 03 |
| Root /tip chord | 381.585 /190.792 mm | Trapezoidal reference chords |
| Mean aerodynamic chord | 296.788 mm | Normalizes static margin |
| Root /tip airfoil | S5010 /E186 | Shape definitions from AeroSandbox; screening in notebook 02 |
| Washout | 2.833° | Solved for modeled trim at requested design condition |
| Pod nominal sizing envelope | 130 ×165 ×560 mm | Width ×height ×length used in sizing; loft stations define actual CAD |
| CAD pod station range | x = −175…395 mm | 570 mm nominal loft length before detailed features; do not equate with the 560 mm sizing proxy |
| Elevon extent, each half-wing | y = 457.90…1076.07 mm | 40–94% of half-span, 22% chord |
| Orin sizing /CAD balance AUW | 3665.72 /3668.22 g | Separate internally reconciled predictions |
| CM5 evaluation AUW | 3435.72 g | Fixed-airframe mass substitution; not a measured second assembly |
| Printed wing /pod /cage | 902.18 /463.54 /123.09 g | Total 1488.80 g, no slicer support/brim allowance |
| Pack | 5S1P, 90 Wh nominal, 390.5 g | Five 5 Ah cells plus 10% pack overhead |

The envelope is a geometric measurement from the STEP assembly, while the
table's aerodynamic dimensions come from the model. Reproduce both separately
when reviewing a dimensional discrepancy. The pod sizing proxy and detailed
loft deliberately use different representations; the effects on mass feedback,
pod drag, and stability correction deserve scrutiny.

The carbon load path uses a straight 14/12 mm OD/ID joiner extending 365 mm per
side, 16/14 mm sleeves, a swept 10/8 mm outer tube from 25–80% half-span, and a
6/4 mm rear anti-rotation pin extending 135 mm per side. Carbon density,
allowable bending stress, and modulus are assumed as 1.55 g/cm³, 400 MPa, and
110 GPa. Supplier-specific allowables and bonded-joint behavior are not inputs
from test. Geometry and clearance construction are in
[fab/geometry.py](../uavdesign/fab/geometry.py); loads are in
[structures.py](../uavdesign/structures.py).

The cage places the lens axis at aircraft x =125 mm. The camera, lens, payload
F9P, antenna, and timing isolation form one rigid structure. Four dampers isolate
the complete assembly from the aircraft. The camera-to-antenna relationship must
remain rigid through vibration; isolating those two items from one another
would invalidate a fixed lever arm. Lens front face is a packaging datum, not a
calibrated optical centre. See [survey_cage.yaml](../payload/survey_cage.yaml).

### Balance and trim are separate checks

The aerodynamic model predicts neutral point x =257.255 mm and target CG
x =239.448 mm. CAD mass accounting instead gives CG x =229.435 mm, yielding
9.374% MAC static margin. Reaching the target with the modeled battery alone
would require its centre at x =124.632 mm. That is outside both permitted
placements: forward x =−25…35 mm with z =−40 mm, or aft x =230…240 mm with
z =−50 mm. The chosen forward battery is clamped at x =35 mm, which fits its
configured shell envelope but leaves the target unmet.

A 5 mm cage shift and a 7% target-margin alternative are evaluated in the
engineering report; neither closes the battery-placement problem. Positive
static margin does not establish satisfactory trimmed control authority,
stall behavior, or handling. Review trim at the attainable CG and loading cases,
then revise layout, aerodynamic choices, or the requirement together. Weigh
the assembled aircraft and measure CG after installation.
[Balance implementation](../uavdesign/fab/build.py),
[stability/trim notebook](../platforms/survey_wing/04_stability_and_trim.ipynb),
[fabrication notebook](../platforms/survey_wing/07_fabrication.ipynb).

## Coordinate, unit, and interface contract

| Domain | Convention | Review consequence |
|---|---|---|
| Aircraft CAD /STEP | mm; x aft from root leading edge, y right, z up | Assembly and individual STEP use aircraft placement |
| Print STL | mm; transformed into configured print orientation and grounded on bed | An STL's coordinates cannot be used directly for an aircraft lever arm |
| Arranged 3MF | mm; source print geometry transformed only by XY translation and rotation about bed Z | Bed optimization preserves the selected build orientation |
| Sizing /performance | SI, with explicitly named mm/g exceptions | Check field suffixes before combining model and CAD outputs |
| Cage local coordinates | mm; lens-front axis datum; x aft, y right, z up; lens points −z | A nominal package datum must not substitute for measured optical centre or antenna ARP |
| Proposed body FLU | metres; x forward, y left, z up, measured FCU origin | Requires translation and axis conversion from aircraft CAD |
| Camera optical frame | named RDF convention in mapping contract | Requires its own calibrated orientation and origin, not just the body sign flip |

For a measured FCU origin `o_cad_mm`, the proposed conversion is
`p_flu_m = diag(-1, -1, 1) @ (p_cad_mm - o_cad_mm) / 1000`.
The origin and cage optical/ARP transforms are unknown until measured. Isolation
can permit cage motion relative to the FCU; a constant transform cannot remove
that motion. The exported mounting template carries these unknowns explicitly.
[Software frame contract](software_spec.md),
[mounting_reference.json](../outputs/review/software/mounting_reference.json).

Keep camera native timestamp, host receipt clocks, GNSS time/event marks, and
FCU boot time distinct. Trigger request, exposure-active edge, and exposure
midpoint are different events. At 16.44 m/s, 1 ms uncompensated timing error
corresponds to 16.44 mm along track. This arithmetic illustrates sensitivity;
the present system has no measured timing-error distribution.

## Analysis methods and their limits

The design chain is implemented in [design.py](../uavdesign/design.py): load
mission/payload inputs, calculate survey speed limits, close free sizing, select
the discrete battery and propulsion masses, solve stability/trim, and evaluate
both payloads on the selected wing. CAD uses that result, estimates printed
mass, and feeds correction factors back into sizing.

| Analysis | Method and implementation | Assumptions a reviewer should challenge |
|---|---|---|
| Imaging | Pinhole footprint, overlap spacing, exposure ×groundspeed /GSD; `survey.py` | Flat ground, nadir view, nominal focal length; excludes distortion, attitude, terrain and image texture |
| Section aerodynamics | NeuralFoil section polars; `aero/airfoil.py` | Training/model fidelity, Reynolds range, transition and surface roughness; predicted polars are not wind-tunnel data |
| Performance | Parabolic drag and finite-wing corrections; `aero/polar.py`, `sizing.py` | Oswald efficiency 0.85, roughness factor 0.15, misc drag, prop/motor/ESC efficiencies, trim/clmax penalties |
| Trim /neutral point | VLM with empirical pod correction; bracketed washout and elevon solves in `aero/stability.py` | Rigid geometry and selected flight condition; Panknin comparison is a second estimate, not validation |
| Mass closure | Iterative mass/area/power coupling plus discrete hardware and CAD feedback | Convergence proves consistency of estimates, not their physical accuracy |
| Printed mass /CG | Adaptive OCC area/volume and separate shell/volume centroids; `fab/massprops.py` | Effective density, walls, infill, double counting around thin features, omitted support/brim/adhesive uncertainty |
| Structure | Numerically integrated Schrenk-like lift, tube section bending, no inertia relief; `structures.py` | Omits skin instability, joint transfer, adhesive peel, stress concentrations, torsion, fatigue and local landing loads |
| Servo | Empirical hinge-load screening with 2× margin in notebook 06 | Dynamic loads, geometry of horn/linkage, friction, backlash and stall-current behavior require hardware evidence |
| Propulsion | Assumed static CT =0.11, CP =0.055, loaded speed 0.80 ×KV ×voltage; `propulsion.py` | These are not measured coefficients for the selected 13×8 folding installation |
| Thermal | Heat balance `m_dot = Q/(cp*deltaT)` and inlet-area estimate; `power.py` | Omits pressure drop, fan curve, recirculation, ground soak and actual heatsink resistance |
| Electrical | Directed power tree with conversion losses; `electronics.py` | Entered typical/assumed-peak loads and nominal rail capacities are not transient qualification |

The printed-mass model is approximately
`rho * [min(A*t, V) + infill * max(V - min(A*t, V), 0)]`,
where `t` is perimeter count ×extrusion width. Area is mm², volume mm³, and
density conversion yields grams. A CAD-derived `measured` field in
`calibration.yaml` means measured *from the geometry model*, not weighed plastic.
Mass factors 1.1493 (wing) and 1.6794 (pod) correct analytic approximations; they
must not be interpreted as empirical material calibration.

The stored calibration reports stable factors and 0.0684% sizing/balance mass
difference against a 1% tolerance. Reusing it with `--no-converge` reproduces a
single build but does not rerun a convergence study. An empty
`convergence.json` from that mode must not be presented as an iteration log.
The builder rejects exhausted convergence and preserves the previously accepted
calibration. Washout/trim solvers reject non-bracketed roots and exhausted solves.

## Performance trade decisions

The Orin case predicts cruise at 13.59 m/s using 92.75 W total electrical power
and 49.44 min endurance. CM5 predicts 13.16 m/s, 72.10 W, and 64.08 min on the same
wing. These estimates include the configured usable battery fraction and model
corrections; they do not allocate every takeoff, climb, turn, transit, and landing
segment of a real mission. Survey-area charts use an upper bound with the
configured on-line fraction and must not be advertised as achieved coverage.

The current 100 m imaging geometry gives 58.31 m across-track footprint,
33.23 m along-track footprint, 17.49 m line spacing, and 6.646 m trigger spacing.
At the blur-limit groundspeed, overlap needs 2.474 Hz. The separate 4 Hz
acquisition request provides a resource budget; it does not prove triggered
capture performance or support an arbitrary wind condition. Worst-case 8 m/s
tailwind adds to cruise airspeed and gives 21.59 m/s groundspeed; only about
2.85 m/s tailwind is available at the existing blur bound and cruise speed.

The bungee trade reduces span to about 1.60 m and area to 0.322 m², but predicts
only 43.82 min and fails the current survey-speed compatibility check. It is an
alternative study, not a chosen smaller replacement. A 5S2P pack predicts
91.75 min but increases AUW to 4.056 kg and required release speed to 12.10 m/s;
its envelope is unvalidated and it fails the selected hand-launch condition.
[Engineering trade output](../outputs/review/engineering_checks.md),
[performance notebook](../platforms/survey_wing/05_performance.ipynb).

## Manufacturing and print-plan review

The CAD pipeline exports 42 individual STEP and STL parts and an aircraft-frame
STEP assembly. The current split policy allows up to 245 mm spanwise sections,
with chordwise splits at 48% chord when a full section will not fit. Wing/elevon
parts retain the chosen span-up build orientation. Locating dowels, tube channels,
joint rings, hatches, magnet pockets, servo access, and damped-cage mounts are
modeled features; inspect them for tooling access and realistic tolerances.
[Fabrication inputs](../platforms/survey_wing/fabrication.yaml),
[part construction](../uavdesign/fab/parts.py),
[assembly sequence](survey_wing.md).

| Profile | Parts | Beds | Entered material /wall /infill /layer |
|---|---:|---:|---|
| Wing skin | 14 | 7 | LW-ASA /1 ×0.50 mm /7% /0.25 mm |
| Pod shell and rings | 5 | 5 | LW-ASA /3 ×0.50 mm /15% /0.20 mm |
| Structural supports, cage, trays and related fittings | 10 | 3 | ASA-CF /4 ×0.45 mm /35% /0.20 mm |
| Hatches | 3 | 2 | LW-ASA /3 ×0.50 mm /15% /0.20 mm |
| Fins | 2 | 2 | LW-ASA /2 ×0.50 mm /8% /0.20 mm |
| Elevons | 6 | 1 | LW-ASA /2 ×0.50 mm /10% /0.20 mm |
| Skids | 2 | 1 | PETG /3 ×0.45 mm /30% /0.20 mm |

The planner reduced 36 beds to 21 using deterministic convex-footprint nesting
and rotation around bed Z. It keeps profiles separate, 8 mm process allowance
per part side, 5 mm between those allowances, and 5 mm edge margin. Thus the
geometry has at least 21 mm model-to-model separation and 13 mm model-to-bed-edge
distance. It does not treat ring interiors or concavities as free nesting space;
21 is a feasible result, not a proven minimum. Real support/brim footprints and
qualified per-object settings could permit further reductions.
[Project input](../print_projects/survey_wing/project.yaml),
[planner](../uavdesign/printing/planner.py),
[printing guide](printing.md).

The current 3MFs contain arranged geometry, not G-code or calibrated material
profiles. Support-bearing pod/hatch profiles have an allowance, not an actual
sliced support envelope. LW-ASA density and flow need coupons, slicer comparison,
and measured parts. Confirm an installed hardened nozzle for ASA-CF: a fabrication
assumption that a nozzle is specified/on order is not installed-hardware evidence.
The project intentionally keeps that confirmation unset until checked.

Review the exported bed pictures and 3MFs, then perform slicing with the exact
machine/material profiles and inspect layer paths, unsupported islands, adhesion,
time and consumption. The local CLI/MCP implements planning, preparation,
slicing and read-only printer queries; it exposes no upload/start operation.
The user must approve the final setup before any physical print starts.

## Electronics, power, and software boundaries

The dedicated BOM chooses an ARK flight controller with independent flight GNSS,
a pitot/differential-pressure candidate, two MKS elevon servos, a Hacker A40-10L
500 KV motor, Castle Talon 60 ESC, and 13×8 folding pusher candidate. The separate
survey payload uses Basler a2A5320-7gcPRO, Kowa 25 mm C-mount lens, survey F9P,
antenna, NVMe, and one computer. Mass and supply/interface confirmation fields
remain visible in [electronics.yaml](../platforms/survey_wing/electronics.yaml)
and [survey_cage.yaml](../payload/survey_cage.yaml); generated BOMs are
[Orin](../outputs/review/electronics/bom_orin.csv) and
[CM5](../outputs/review/electronics/bom_cm5.csv).

The battery directly feeds propulsion and the flight controller and feeds
separate compute and servo converters. Camera power is assigned to the FC 12 V
rail; compute/NVMe use the compute rail, with F9P and datalink load propagated
through the companion USB supply. Typical non-propulsion pack loads are 37.75 W
Orin and 22.19 W CM5; assumed servo peak raises them to 50.25/34.69 W. They must
not be added twice to the total cruise predictions. No exact pin-by-pin harness
has been released because several board/carrier/regulator selections remain
open. The CM5 module itself does not accept 12 V; the selected carrier must
accept that rail or the converter budget must change.
[Hardware specification](hardware_spec.md),
[power budget](../outputs/review/electronics/power_budget.json),
[open items](../outputs/review/electronics/open_items.txt).

The thermal screen requests 1.196 L/s air for 20 W and a 15 K rise, with a
176 mm² nominal inlet under its capture assumption. It explicitly requires a
ground fan; this result proves neither duct pressure drop nor heatsink adequacy.
Full-charge current screening is 40.16 A, or 48.19 A with the chosen 20% ESC
headroom, below the 60 A entry. Continuous thermal behavior, low-voltage thrust,
folded/deployed blade clearance, and shaft/hub suitability still need evidence.

Mapping functionality belongs in the adjacent repository. The design exporter
produces a sealed handoff, camera geometry profile, platform registry, and
nominal mounting template. It does not implement acquisition or navigation.
The inspected mapping revisions support the existing OAK/PX4 path; the proposed
GigE/event adapters and Plane mission checks are tracked by
[camera/event request](../integration/feature_requests/01_camera_event_adapter.md)
and [fixed-wing request](../integration/feature_requests/02_fixed_wing_handoff.md).
Their inspected revisions are recorded in the profile; review current upstream
code separately before asserting its present capabilities.

At 5320 ×3032 pixels, Bayer8 and 4 Hz, the raw budget is 64.52 MB/s. The exporter
requests at least 83.88 MB/s sustained write rate after the 30% margin and
244.19 GiB free space for the 50-minute requested interval plus 62 s warmup/postroll
and 5 GiB reserve. Capacity and throughput measurements are null. Unpacked
16-bit data doubles raw bandwidth and cannot be accepted unchanged under the
configured 1 Gb/s link budget. Optional Orin preview must not starve the recorder;
the historic “live mosaic” payload label is not a qualified implemented feature.
[Software specification](software_spec.md),
[validation blockers](../outputs/review/software/validation.json).

## Notebook reading order and review questions

The notebooks are generated from
[scripts/nbdefs/survey_wing.py](../scripts/nbdefs/survey_wing.py); edit that source,
regenerate, and execute in fresh kernels. Outputs in the review package are
evidence from a recorded execution, while checked-in notebook files are the
reproducible analysis source. Inspect cell inputs as well as rendered figures.

| Notebook | Inspect and challenge |
|---|---|
| [01 Requirements and payload](../platforms/survey_wing/01_requirements_and_payload.ipynb) | Imaging geometry, blur/frame-rate limits, payload alternatives, optimistic coverage, storage budget |
| [02 Airfoil selection](../platforms/survey_wing/02_airfoil_selection.ipynb) | Reynolds/CL basis, drag and pitching-moment comparisons, reflex/thickness trade, model limits |
| [03 Sizing closure](../platforms/survey_wing/03_sizing_closure.ipynb) | Free versus discrete-hardware sizing, component mass allocation, AR and launch trade, CAD correction influence |
| [04 Stability and trim](../platforms/survey_wing/04_stability_and_trim.ipynb) | Neutral point/pod correction, twist root and residual, tip alternatives, attainable versus requested CG |
| [05 Performance](../platforms/survey_wing/05_performance.ipynb) | Power above stall, launch/climb requirements, pack substitution, endurance versus actual mission segments |
| [06 Structures](../platforms/survey_wing/06_structures.ipynb) | Lift distribution, bending stations, spar routes, reserve factors, omitted joint/torsion failure, servo assumptions |
| [07 Fabrication](../platforms/survey_wing/07_fabrication.ipynb) | CAD manifest and pictures, density/perimeter assumptions, mass and CG accounting, physical battery placement |
| [08 Electronics](../platforms/survey_wing/08_electronics.ipynb) | Rail hierarchy/losses, open SKUs, nominal and low-pack propulsion, thermal assumptions, unsupported software |
| [09 Mission and balance sensitivity](../platforms/survey_wing/09_mission_and_balance_sensitivity.ipynb) | Wind/imaging feasibility, explicit mission-time allocation, attainable battery movement and resulting CG |
| [10 Manufacturing and review audit](../platforms/survey_wing/10_manufacturing_and_review_audit.ipynb) | Manufacturing scale, part/profile inventory, print-bed atlas, artifact identity and evidence gaps |

The review index links all ten executed survey-wing notebooks and their execution
records, together with additional annotated CAD figures. Use the generated
inventory to identify what was actually executed for the package you received.

Before recommending a next physical build, an external reviewer should resolve
which CG/trim revision to pursue, whether Orin's endurance and downwind imaging
requirements change, and what measured propulsion/material evidence controls
launch and structural decisions. Findings should distinguish an implementation
error, a design requirement shortfall, a modeling assumption, and missing
physical evidence. The [review protocol](external_review.md) gives the structured
report format and reproducible commands.
