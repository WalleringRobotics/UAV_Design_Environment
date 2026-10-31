# Revised interface dry fits - Rev1

Print these after the small bore/insert coupons. They are independently designed
prototype interfaces for the survey wing. STL units are mm; use supplied print
orientation. No G-code or printer-specific calibrated presets are included.

## Servo first

Print `02_servo_tray_R_Rev1.stl`, `02_servo_clamp_R_Rev1.stl` and
`02_servo_cover_R_Rev1.stl`. PLA is adequate to inspect geometry on the bench;
load/clamp/bond evidence requires the final structural material/profile.
The aircraft's current profile is ASA-CF, four 0.45 mm walls, 35% gyroid,
0.20 mm layers; confirm the correct installed nozzle. Do not assume a PLA
test is equivalent to that process.

Use the actual MKS HV6100, horn, link and cable. The clamp uses two M2 screws
and candidate inserts, nominal OD3.5 x height4 mm; verify supplier dimensions
and pilot installation before fitting. M2x6 is a prototype length requiring
thread-engagement/bottoming inspection. Keep the body restrained without case
distortion. Check output shaft/ears, wire exit, full throw, backlash and current.
The cover is taped down for access and carries no control load. Repeat the
complete check inside a representative wing section before powered load tests.

## Root bridge next

Print `02_pod_root_anchor_R_Rev1.stl`, `02_wing_root_anchor_R_Rev1.stl`
and `02_wing_root_bridge_R_Rev1.stl` in the same intended rigid profile.
The bridge joins one M3 screw into each bonded hardpoint. Candidate M3 inserts
are OD5 x height5 mm, with M3x8 screws; first qualify pilots with the initial
coupon. Verify engagement, bottom clearance, accessible screw heads and visible
seating. Carbon tubes are not drilled for retention.

The two `03_*seat_fit_fixture*` files are small CROPS of the actual wing and pod
seats, intended to check bonding clearance and access cheaply. They are NOT
whole root parts or a representative complete carbon/skin load path. Match
their aircraft materials/orientations for a bond-process trial: wing LW-ASA,
one 0.50 mm wall/7% gyroid/0.25 mm layer; pod LW-ASA, three 0.50 mm walls/15%
gyroid/0.20 mm layer, subject to qualified slicer settings and supports. New crop
faces alter printed end caps, so do not use patch weight to calibrate the full
wing. Do not use these cut-down fixtures to claim assembled wing strength.

Dry-fit anchors, bridge and seats before bonding. Record bond gap and retention
fit. The later full root/skin/sleeve/spar assembly needs load tests in axial
retention, bending and torsion with appropriate fixture loads, then inspection
for peel, skin buckling, creep and cracks.

## Records and provenance

Record specimen revision, material, machine/nozzle, drying, settings, dimensions,
mass, hardware, adhesive/prep/cure, fixture, applied loads and failure mode.
The pack includes a source manifest identifying the whole-aircraft export.
Regenerate only after the current full CAD/review export:

```bash
python scripts/build_parts.py --review-out outputs/review
python scripts/build_verification_pack.py --interfaces
```

These commands export files. They do not start a print or qualify a flight part.
