# Independent survey-wing build improvements

31 October 2026. The chosen development route is our own aircraft. Building
Moose is not a prerequisite. Keep the 2.3 m tailless/pusher architecture and the
camera/GNSS reference concept while closing concrete assembly and launch work.
This supersedes the earlier recommendation to build a separate reference aircraft.

The baseline review was at `c05f36d`. Its 42-part counts, 21-plate plan and mass
are historical after these mechanical changes. Rebuild and use the current
manifest, calibration, `development_checks.json` and arranged print plan together.

## Work register

| Priority / finding | Design improvement in this change | Evidence still needed and closure |
|---|---|---|
| 1 / REV-RET-001, wing attachment | Two separate bonded hardpoints and a bolted bridge per root; shared hole/seat datums; no holes drilled in carbon. Fasteners are accessible and independent of the spar's sliding fit. | Actual insert/pilot and bond qualification; root seating and tool access; load the retained root in axial pull, bending and torsion. A valid solid is only a CAD result. |
| 1 / REV-SERVO-001, servo load path | Structural cassette with a floor and locating walls; removable forward clamp; M2 fasteners/inserts. The taped cover remains non-load-bearing. A new branch connects the existing spanwise wire channel to the cassette. | Check the real MKS body, ears, output shaft, lead exit and case clamping; link geometry, backlash and full motion; reverse hinge loads and servo current. |
| 1 / control surfaces | Existing horn pad, segmented elevon reinforcement and tape hinge retained; dry-fit them with the cassette rather than choosing horns by appearance. | Select the actual horn, pushrod and hinge process. Verify both pitch and roll commands together, free motion and stopping before mechanical interference. The original 20-degree servo screen is a test reference, not a flight-qualified throw. |
| 1 / REV-CG-001, balance | New attainable-CG trim report for BOTH Orin and CM5 on the actual generated assembly. It uses each configuration's installed moment balance, not the intended 6% point. | Choose an accepted CG/loading range supported by trim and control reserve, then measure real mass/CG. Original 6% target remains visible and is not silently declared achieved. |
| 1 / REV-LAUNCH-001, launch | Keep hand launch as the existing selected requirement, with a separate model-derived loaded-voltage screen and explicit bench tasks. Bungee remains an alternative requiring a decision and designed load path. | Actual thrust/current/RPM/pack-sag curves; measured/justified release technique and grip/prop path; low-speed trim/control evidence. Do not use the model voltage as an automatic launch permission. |
| 1 / REV-STRUCT-001, joints | Carry generated mass into force and root-moment targets; first tests focus on the joiner/sleeve, swept-spar transfer, pod/root hardpoints and chordwise bonds. | Supplier carbon data and final-material/process coupons; combined bending/torsion/peel/axial joint tests, local buckling, fin and landing loads. Axial and torsional acceptance loads are still to be derived. |
| 2 / REV-MFG-001, printing | New small test pack: bore gauges, insert pilots, density, thin-wall and bond specimens; small interface dry-fits precede full airframe prints. | Sliced paths, measured dimensions/mass and test-to-failure observations. Lower-infill variants may be compared but default whole-wing settings are not reduced without evidence. |
| 2 / propulsion installation | Retain current pusher arrangement. Confirm selected motor cross, shaft/hub, bolt lengths, brake and folded-blade stop geometry before installation. | Vendor/physical geometry and both folded/deployed clearance through rotation. The existing deployed-plane check does not prove folding compatibility. |
| 2 / payload, battery and landing | Preserve rigid camera-to-GNSS relationship with isolation below the complete cage. Keep battery straps/stops, skids and window protection in the installation review. | Actual connector bends, 55 mm lens knurl/screw keep-outs, cage motion, window/view clearance, pack retention and skid/ground clearance. Dummy payload must reproduce mass AND position and use a retained mount. |
| 2 / REV-SYSTEM-001, power/thermal | Existing independent FC/servo/compute power tree retained. Review removable cable routing with the new joints and final carrier/regulator choices. | Final SKUs and pin-by-pin harness; polarity/continuity; servo stall/inrush, low-pack regulation, ripple and temperatures at ground idle and in cooling flow. CM5 module is not a 12 V load without a suitable carrier. |
| 3 / REV-IMAGING-001, wind and blur | New exposure-candidate report gives required capture rate and a shutter bound at the configured tailwind. Test 0.25 ms (1/4000 s) as the first alternative. | Representative sharpness/noise/lighting and sustained event-aligned capture. Configured 0.4 ms remains unchanged until image evidence supports a replacement. |
| 3 / REV-ENDUR-001 and mapping | Preserve 50-minute full mission objective; make short development flights a separate objective. | Segment energy/reserve and measured consumption; full recorder/thermal soak, timing calibration, reference station/datum, and independent checkpoints. No requirement is removed merely to make the report green. |

The Moose-bay camera-fit finding is no longer a dependency for this route. Our
own camera installation remains subject to the packaging tests above.

Shorter exposure alone is not the whole wind solution: at the old 13.59 m/s
cruise plus 8 m/s tailwind, about 3.25 Hz is required. That fits a raw 4 Hz cap
but slightly exceeds the sizing model's 80% rate allocation (3.2 Hz). The new
report therefore exposes a minimum cap of about 4.06 Hz at that loading. A
5 Hz candidate is within the camera's published 7 Hz limit, but acquisition,
link, storage, thermal and timing evidence must be re-budgeted before adopting
it. Limiting the wind/track envelope is the alternative; the original contract
is not silently changed. Rebuild after mechanical/mass changes for new numbers.

## Prototype attachment details

![Prototype root bridge and bonded anchors; fasteners omitted](images/wing_root_retention_Rev1.svg)

![Prototype servo cassette and forward clamp; servo omitted](images/servo_cassette_Rev1.svg)

### Wing roots

Each side has a rigid `pod_root_anchor`, `wing_root_anchor`, and
`wing_root_bridge`. Both M3 screws must be fitted. The bridge spans the root
joint with one screw in each hardpoint; no retention relies on a tight carbon
fit. The insert pilots and 0.2 mm nominal bond gap are calibration candidates.
Check that both root faces are seated before tightening. Do not use the screws
to pull an incorrectly seated sleeve onto the joiner.

The hardpoint seats are placed between the joiner and rear-pin stations using
shared geometry datums. They are cut into the mating pod/wing; the bridge has
a corresponding passage. Bond quality and transfer into skin/local structure
control performance. A metal insert's strength does not establish the surrounding
printed or bonded joint strength. The bridge introduces a new local load path
that must be tested as an assembly before it is accepted for flight.

The subsequent margin review extends the joiner to 400 mm per side and uses
a 14/10 mm tube (2 mm wall) rather than the former 14/12 mm tube. The sleeves
retain their 16/14 mm section, preserving the nominal sliding interface. The
longer overlap reduces the outer-tube bending demand; the thicker joiner
restores the root bending screen. Actual carbon layup and allowables still need
supplier data/test evidence. A dimensional supply candidate is
https://www.carbon-composite.com/en/Carbon-High-Precision-Tube-2mm-OE-14mm-x-oe-10mm/CT014010
; no stock, price or strength rating is assumed from that link.

The aft pod station, firewall, motor and propeller datums move aft together by
15 mm to recover deployed-plane clearance on the resized wing. This is a
coherent installation translation; it does not qualify the actual folding hub
or blade clearance.

### Servo cassette

The cassette flange/walls are bonded into a larger pocket. A forward strap with
two M2 screws restrains the servo body while leaving the aft arm/link area open.
A 0.2 mm pad/shim allowance is an initial fit value. Installation must restrain
the body without distorting its case. Do not support control loads on the cover.

The MKS European table lists HV6100 dimensions 22.5 x 10 x 23.8 mm and 10 g:
https://mksservo.eu/en/category/glider-series/ . The MKS USA listing gives
23.5 mm for the last dimension, so use the actual unit to check the body,
ears, shaft and lead. The cassette is an adjustable body-clamp prototype,
not a vendor-certified mounting drawing.

## First print order

1. [Process coupons](first_prints.md): carbon fits and inserts first, then wall,
   mass and bonds. PLA may check geometry; final material is needed for load data.
2. One servo cassette, clamp and cover. Fit a real servo, lead, horn and pushrod.
3. One root bridge and hardpoint set, followed by a root/pod-side representative
   assembly with real carbon and the intended bonding process.
4. One representative joined wing section and a pod/cage fit assembly; slice,
   weigh and update the model before printing the complete airframe.

Use `python scripts/build_verification_pack.py` for the first small STLs.
Use `python scripts/build_parts.py --review-out outputs/review` after changes
to update the assembly and calibration. A complete CAD rebuild is necessary
before using any revised aircraft-frame STLs. None of these commands prints.

## Proposed development stages

**Process samples:** fit, mass and material observations. No aircraft flight
claim is made. This is useful work to start immediately on the existing printer.

**Retained and powered subassemblies:** qualified bond/insert process, root
retention, controls, propulsion and power/thermal bench evidence. Close assembly
and control interference before committing to the complete printed set.

**Short aircraft development flights:** selected launch method, measured mass/CG,
control directions/travel, retained battery/payload, structural evidence and
power checks. Keep the original payload mass case or explicitly re-evaluate
the dummy/light configuration. Survey accuracy and 50 minutes are not entry
criteria for this limited test, but recovery and reserve still need planning.

**Survey demonstrator:** qualified capture, wind/exposure envelope, time/lever-arm
calibration and mission energy. The same original aircraft can progress here;
building a different company's airframe is not required.

## Test records

Record actual material, settings, geometry revision, load/fixture, displacement
and failure mode. Until measured, quantities remain unknown. The exported load
targets apply to the stated lift-distribution model; distributing fixture loads
to reproduce bending, shear and torsion is part of fixture design. A single
weight at an arbitrary wing station is not an equivalent structural test.

Open design questions are finite: accepted CG and control reserve; actual
launch capability; axial/torsional joint targets; final motor hub, regulator,
carrier and connector geometry; calibrated process; and measured mission
performance. This change provides prototype geometry and repeatable calculations
for those decisions. It does not represent unperformed physical tests as passed.

## Rebuild results for this prototype revision

The saved calibration converged in two iterations. The generated assembly has
52 valid, connected parts, all within the configured Core One build volume.
Orin CAD mass is approximately 3.733 kg (about 65 g above the reviewed 3.668 kg
baseline), with a resized aerodynamic span of 2.310 m. This includes feedback
from the new mounting parts; it is still a predicted mass, not weighed plastic.

| Configuration | Attainable modeled CG | Static margin | Modeled cruise elevon |
|---|---:|---:|---:|
| Orin | 231.82 mm | 9.27% | -1.74 deg (up) |
| CM5, nearest configured bay chosen by the balance solver | 250.70 mm | 2.97% | +1.74 deg (down) |

Both cases have linear-model trim roots, but the CM5 result highlights a new
configuration concern: the solver selects the aft battery bay and its static
margin is below the 4% lower value used in the existing numerical CAD screen.
Do not interpret lighter compute as an automatically acceptable first-flight
configuration. Rework its layout, or use a retained mass-equivalent dummy for
the accepted heavier installation and remeasure CG. The original 6% target
remains unmet in both current bay choices; no CG interval is flight-approved.

Exported STEP collision checks found no positive-volume interference between
the new anchors/bridges/cassettes/clamps and the wing, pod or servo cover. This
does not establish adhesive quality, tool access with real hardware, strength,
creep or case-clamping behavior. Those are the next physical checks.
