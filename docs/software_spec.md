# Survey software specification and design handoff

Revision: 2026-10-10. Software owner: [WalleringRobotics/mapping_functionality](https://github.com/WalleringRobotics/mapping_functionality).

The existing OAK-D/PX4 platform is real hardware with a working recording path.
Preserve it. The survey wing is a **new, additional platform**, using ArduPilot
Plane, independent flight GNSS and a rigid camera/survey-GNSS cage. Basler is the
preferred camera candidate, not a mandatory dependency. Orin and CM5 are separate
compute configurations of the new aircraft. This repository owns design budgets,
mechanical/electrical exports and the handoff contract; acquisition, mission
association, calibration, processing and map QA belong in `mapping_functionality`.

## Inspected software, including unmerged work

The review used source files through the GitHub connector; it did not run the
mapping application's ROS/hardware suite. Immutable revisions:

| Revision | Inspected evidence | Status and consequence |
|---|---|---|
| [`51a3d3237cd6033146b8d0d472d4ff15c1c68dc6`](https://github.com/WalleringRobotics/mapping_functionality/tree/51a3d3237cd6033146b8d0d472d4ff15c1c68dc6) | `README.md`, `AGENTS.md`, `docs/architecture.md`, `docs/dataset-format.md`, `docs/rosbag-recording.md`, `docs/roadmap.md`, `src/wallering_mapping/cli.py`, `rig_calibration.py`, `configs/oakd-ros.yaml`, processing recipes | Main: ROS Humble/depthai/MAVROS/MCAP acquisition; offline COLMAP/ODM; OAK/PX4 calibration. Existing functionality stays supported. |
| [`b8e48cc1f0ee1b4e5c22afcfe68afd74e17dcb36`](https://github.com/WalleringRobotics/mapping_functionality/tree/b8e48cc1f0ee1b4e5c22afcfe68afd74e17dcb36) | PR [#24](https://github.com/WalleringRobotics/mapping_functionality/pull/24), changed-path comparison, `docs/roadmap.md` | Unmerged, seven commits ahead: adds x86 OpenSfM using the pinned ODM image and stronger product validation. Do not describe it as available on main. |
| [`5f8f55b59cb0b61b3ca7cee46c83f32443c36632`](https://github.com/WalleringRobotics/mapping_functionality/tree/5f8f55b59cb0b61b3ca7cee46c83f32443c36632) | PR [#25](https://github.com/WalleringRobotics/mapping_functionality/pull/25), `docs/first-flight-plan.md` | Unmerged, five commits ahead: reports a completed 20-minute default soak and weak TIMESYNC qualification. This is reported evidence, not independently remeasured here. Its Tarot-only airframe assumptions predate the new wing. |
| [`ab05b427e1ed650af858349e01c8294861af4016`](https://github.com/WalleringRobotics/mapping_functionality/tree/ab05b427e1ed650af858349e01c8294861af4016) | PR [#26](https://github.com/WalleringRobotics/mapping_functionality/pull/26), `survey_plan.py`, `docs/survey-planning.md`, `configs/qgc-oak-rgb-12mp.json` | Unmerged, one commit ahead: QGC Survey validation, mission binding and leg selection; explicitly PX4 multirotor/OAK only. Preserve that refusal until fixed-wing support is implemented. |

All 15 listed branches were considered against main. The other eleven non-main
branches are ancestors of main; they contain no additional unmerged commits.
No mapping branch was modified or merged by this design exporter.

Main's production OAK profile requests RGB 4056×3040 and two 1280×800 mono streams
at 2 fps, OAK gyro 200 Hz with 250 Hz acceleration interpolated onto gyro stamps.
The 20 fps profile remains a candidate. PR #25 reports 74.6 MiB/s mean writes,
about 99 GiB per 20-minute session and only 26/11,999 qualified TIMESYNC samples.
These findings qualify that specific OAK setup only; they establish neither
Basler/CM5 throughput nor survey accuracy. Existing calibration issues
[#6–#16](https://github.com/WalleringRobotics/mapping_functionality/issues/15)
and recorder loss [#18](https://github.com/WalleringRobotics/mapping_functionality/issues/18)
remain the appropriate places for the OAK acceptance work.

## Critical corrections to the hardware/software plan

1. **The old camera identifier was inconsistent.** The previous a2A5328-4gcPRO
   entry should not be treated as an IMX542 specification. The current preferred
   candidate is the [Basler a2A5320-7gcPRO](https://www.baslerweb.com/en/shop/a2a5320-7gcpro/),
   with dimensions/rates carried by the corrected design YAML. Generated exports
   always derive their pixel counts and camera name from that YAML. Preserve an
   exact SKU, selected pixel format and measured triggered rate together.
2. **A camera definition is not an acquisition adapter.** Main hardcodes OAK
   sockets/frame names and PX4 clock relationships. A Basler cannot be substituted
   by renaming OAK topics or supplying a different JSON camera. Add a camera
   capability profile and adapter while keeping the OAK path intact.
3. **Camera maximum rate and requested recording rate differ.** The preferred
   camera may support 7 fps in a particular mode; the proposed acquisition profile
   budgets 4 fps. At approximately 16 MP, Bayer8 at 4 fps is about 64.5 MB/s.
   A 16-bit unpacked mode is about 129 MB/s, exceeding even ideal 1 Gb/s Ethernet
   before overhead. Packed modes, packet sizing and measured sustained performance
   need explicit qualification. Export the rejection, not a silently lowered rate.
4. **The Orin “live mosaic” label is a target capability.** The mapping architecture
   is offline reconstruction. Orin initially runs ingestion, integrity monitoring
   and optional bounded QA thumbnails; CM5 runs ingestion and logging. Live
   mosaicking is deferred until profiling shows headroom and navigation quality
   is adequate. A preview must never starve the immutable recorder.
5. **Fixed-wing speed is an airspeed/groundspeed problem.** At 100 m AGL, 2.74 µm
   pixels and a 25 mm lens, nominal GSD is 10.96 mm/px. A 0.4 ms exposure and
   0.6 px blur limit give 16.44 m/s maximum groundspeed; changing shutter, altitude
   or camera changes that limit. Aircraft stall margin constrains airspeed.
   A tailwind may make both constraints impossible simultaneously: the planner
   must refuse that combination, never command a speed below the aircraft limit.
6. **CAD placements are not calibration.** Lens-front and package-envelope datums
   are not the lens perspective centre or antenna ARP. The rigid cage preserves
   the camera–antenna relationship, but measured offsets, boresight, uncertainty,
   and any motion of the isolated cage relative to the FCU remain required.

## Exported contract

Run from this repository:

```bash
python -m uavdesign.integration --output outputs/mapping-handoff
```

Use a fresh output directory. The command exports a deterministic, sealed set:

| File | Consumer and meaning |
|---|---|
| `mapping_handoff.json` | Versioned design request; source hashes, camera/compute/flight hardware, mission targets, raw bandwidth/storage calculations and explicit unsupported capabilities |
| `handoff.schema.json` | JSON Schema 2020-12 shape/units; `uavdesign.integration.validate_handoff` also checks numerical consistency |
| `camera_profile.json` | Nominal QGC Custom Camera fields in the field structure inspected in PR #26; not a flight plan and not currently a supported Basler recorder profile |
| `platform_registry.json` | Distinguishes existing OAK/PX4 from the new wing; keeps Basler as a substitutable preferred candidate |
| `mounting_reference.json` | CAD/FLU convention and explicit unknown measurement fields; never presented as OAK rig calibration |
| `validation.json` | Contract validity plus unsupported/unmeasured blockers; `survey_ready` remains false |
| `software_spec.md`, `SHA256SUMS` | Reviewable requirements and artifact integrity |

The input profile is `integration/mapping_profile.yaml`. Aircraft/camera dimensions
come from `platforms/survey_wing/design_point.yaml`, component identities from
`electronics.yaml` and `payload/survey_cage.yaml`. Both compute variants appear.
The default 50-minute integration window is an **endurance requirement**, not an
achieved endurance prediction. A future concrete flight request must use the
selected battery/configuration's achieved endurance with climb, transit, turns,
wind and return reserve deducted. Generated geometry assumes flat ground, nadir
view and the sensor long side across track; it is planning geometry only.

Storage is conservatively calculated at requested camera rate for the full
capture interval plus warmup/post-roll, a 30% margin and a 5 GiB reserve. Capacity
and sustained-write evidence are null until measured. Actual disk occupancy,
GNSS/telemetry rates, filesystem overhead and workstation scratch space require
separate checks. No image, GNSS coordinate, timestamp, calibration or checkpoint
is invented by this exporter.

## Additive capabilities required in mapping_functionality

| ID | Requirement | Executable acceptance |
|---|---|---|
| SW-01 | Load versioned platform/camera profiles and the sealed design handoff; bind the exact hashes into every new session | Unknown versions, altered files, unsupported adapters and inconsistent units fail before acquisition; existing OAK fixtures remain valid |
| SW-02 | Add GigE global-shutter acquisition, initially the selected Basler candidate; keep raw pixels, GenICam/Pylon settings, serial/firmware, native frame counter and camera timestamp domain | Replay-backed adapter tests cover frame/packet loss, counter wrap/restart, timestamp reset, device unplug, disk full and interrupted stop; final hardware full-duration soak retains the evidence |
| SW-03 | Preserve camera ExposureActive/trigger events and independent survey F9P raw observations | Raw bytes and decoded RAWX/SFRBX/TIM-TM2 records retained; associate images/events by explicit counters/edges with missing/duplicate/out-of-order/wrap tests; never substitute receipt time for exposure |
| SW-04 | Generalize rig/time contracts without reusing OAK/PX4 names for another device | Versioned named frames; optical centre and antenna ARP in metres with uncertainty; clock equations include event edge, latency, polarity, GNSS time system/week/leap-second handling and evidence; unknown remains unknown |
| SW-05 | Support ArduPilot Plane plan checks alongside PX4 multirotor | QGC/Mission Planner saved fixtures plus Plane SITL validate start, mission indexing, abort, landing and recording association; reject inadequate stall margin, insufficient turn radius, wind-induced blur/overlap violation, geofence crossings and duration excess |
| SW-06 | Reuse image export and offline reconstruction engines | A real multi-view dataset from each accepted adapter passes original/derived hash checks, calibrated camera conversion, reconstruction, coordinate/datum checks and held-out checkpoint reporting |
| SW-07 | Compare Orin and CM5 operation under the identical input contract | Independent full-duration thermal/write-rate/resource reports for each final carrier and drive; optional processing load never reduces acquisition guarantees |
| SW-08 | Produce reviewable final survey products with honest qualification | Orthomosaic/DSM GeoTIFF, LAZ, mesh where supported, image/pose inventory, independent accuracy report, processing revision/configuration, provenance and product checksums; missing references prevent an absolute-accuracy claim |

## Timing and frame contract

Keep the native camera clock, host receive monotonic/UTC clocks, survey-receiver
GNSS clock and flight-controller boot clock distinct. External trigger submission,
ExposureActive edge and exposure midpoint are separate events. Measure exposure
latency/jitter and optocoupler delays; qualify electrical levels and edge polarity
against the installed hardware before claiming a common time reference. At
16.44 m/s, 1 ms uncompensated error corresponds to 16.44 mm along track; this is
an error-budget term, not a demonstrated accuracy.

The CAD convention is x aft, y right, z up in millimetres. For a measured FCU
origin `o` in the same CAD frame, `p_flu = diag(-1,-1,1) @ (p_cad-o)/1000`.
The origin must be supplied. Camera optical RDF axes require their own measured
rotation and optical-centre offset. A damped cage's body-relative flex cannot be
removed by a static transform. Preserve any attitude/lever-arm uncertainty in
image geolocation and checkpoint budgets.

PPK input consists of rover observations/navigation, event marks and independent
base/CORS data with an explicit reference datum. “RTK fixed” status alone does not
replace those observations. The F9P survey chain must not become a navigation
dependency of the independent flight GNSS. Capture cannot arm the aircraft,
upload a flight plan, or change persistent FCU/receiver parameters implicitly.

## Delivery sequence and evidence

First land the versioned adapter/profile interface and design-handoff ingestion
with regression coverage for the existing OAK/PX4 platform. Implement candidate
GigE/event ingestion using saved vendor records; implement Plane checking using
saved plans and SITL. These software activities do not require a camera purchase.
Then qualify actual selected camera/compute hardware, measured timing and cage
calibration. Finally reconstruct a real moving survey with independent controls
and checkpoints. A printed aircraft and a passing Python test suite cannot supply
those physical datasets.

The feature-request drafts under `integration/feature_requests/` extend the
inspected upstream work. They do not replace existing calibration issues, PR #24
processing work, PR #25 field planning, or PR #26 QGC integration. No new survey UI,
flight-controller implementation or photogrammetry engine is proposed.
