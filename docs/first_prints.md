# First prints - independent survey wing, Rev1

Start with process coupons. Do not print the full airframe using the old
calibration while attachment revisions are being developed. Files in the first
verification pack are test pieces, not flight parts. STL units are millimetres.

## Print now: small coupons

| Order | File | Setting and quantity | Measure / decision |
|---|---|---|---|
| 1 | `01_tube_14mm_diametral_gauge_Rev1.stl` | 1; intended rigid fitting material; flat as supplied; no supports | Test the actual 14 mm joiner. Select a free sliding fit without shake; record tube OD, chosen labelled diameter, force/feel, material and settings. |
| 2 | `01_tube_16mm_diametral_gauge_Rev1.stl` | 1; intended wing material/profile | Test the actual 16 mm sleeve OD in a bonded socket. The selected adhesive determines its bond-line requirement. Do not use a sliding fit as an adhesive specification. |
| 3 | `01_M3_insert_pilot_gauge_Rev1.stl` | 1; intended rigid fitting material, fitting profile | Use the actual OD 5 x height 5 mm M3 insert. Label is PILOT diameter, not thread size. Compare 4.6, 4.8, 5.0, 5.2, 5.4 mm pilots; check cracks, bulging, tilt, bottom protrusion and screw engagement. Record axial pull and torque test results before adopting a pilot size. |
| 4 | `01_density_20x20x10_Rev1.stl` | 1; chosen foaming material; 100% infill; record all settings | Nominal envelope is 4 cm3. Weigh after cooling; apparent envelope density = mass_g/4. This is an initial process check, not a complete wing-mass calibration. |
| 5 | `01_wall_mass_30x30x20_Rev1.stl` | Start with 1; same extrusion width/layer/flow/cooling as intended wing; one perimeter, 0% infill, no top, three bottom layers | The input STL is solid so the slicer controls the walls. Inspect missing paths, consistency and layer adhesion. Weigh and compare repeats; do not infer density directly from this hollow print's outside volume. |
| 6 | `01_bond_strip_print_twice_Rev1.stl` | Print 2 per joint; intended material and aircraft-equivalent layer orientation | Bond a 20 x 20 mm overlap, using the chosen surface prep, adhesive and documented full cure. Record dimensions, failure load and where failure occurs. The loaded end holes are simple fixture points, not rated test-machine fittings. |

Other bore gauges cover 3, 6 and 10 mm features. Print only the diameters you
have matching hardware for. A measured tube can differ from its nominal size.
All gauge bores are vertical in the supplied orientation; horizontal/oblique
bores require another representative test. Labels such as +0.3 mean 0.3 mm
added to DIAMETER, not 0.3 mm on each side. Record a labelled candidate that
fails as well as one that works; do not automatically choose the tightest.

PLA is useful for a quick fit exercise. Load, creep, bond and insert results
must come from the final material, orientation, moisture/foaming state and
process. CF grades require the appropriate installed nozzle. Use the selected
printer/material profile; exact foaming speed, temperature and flow still need
calibration. The pack contains geometry, not printer-specific G-code.

The original fit assumptions include 0.25 mm radial tube clearance (0.50 mm
diametral), 3.2 mm alignment bores and 5 mm OD M3 inserts. Coupons bracket those
assumptions rather than asserting they are correct. Insert supplier installation
instructions control installation temperature and pilot selection.

## Next: revised small assemblies

After the coupons, dry-fit the revised servo tray/clamp/cover with the real
servo, horn and link. Check body play, full travel, screw engagement, clamping
without case distortion, wire bend radius and whether the cover closes. Load
the linkage in both directions while watching servo/body movement.

Then print a wing-root/retention/pod-side test assembly. Fit the real tubes,
anchor blocks, bridge plate and fasteners. Check complete root seating, tool
access, release and visible engagement. Test axial retention separately from
bending and torsion. A successful insert coupon is not a qualified wing joint.

Do not print the full pod, cage, complete wing or fins until these tests have
informed the released geometry and material profiles. Representative loaded
wing/pod joints, material creep, environmental conditioning and adhesive
failure modes remain separate tests before flight.

## Record each specimen

Record: specimen/file revision, material/lot, drying, nozzle, layer direction,
layer height, extrusion width, temperature, flow, speed, cooling, infill/walls,
actual dimensions, mass, adhesive/prep/cure, hardware part and measured size,
load application/fixture, test load, displacement, failure mode, photos, date.
Keep observations as measurements, not a generic pass tick. Initial coupons
select a process; acceptance loads for the complete joint come from its load
case and tested assembly, not the small coupon's best result.

Regenerate with `python scripts/build_verification_pack.py`. No files are sent
to a printer and no print is started by that command.
