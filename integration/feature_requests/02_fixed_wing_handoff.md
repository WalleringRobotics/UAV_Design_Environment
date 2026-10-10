# Extend survey plan validation to ArduPilot Plane using versioned aircraft/camera limits

Preserve the real OAK/PX4 multirotor platform. Add the new dedicated survey wing
as an explicit second platform with ArduPilot Plane, independent flight GNSS,
Orin/CM5 compute variants and a substitutable camera (Basler preferred).

Evidence: PR #26 at `ab05b427e1ed650af858349e01c8294861af4016` implements QGC
Survey checking and recording/leg association, but `survey_plan.py` explicitly
accepts PX4 multirotor only and reads an OAK ROS camera profile. PR #25 at
`5f8f55b59cb0b61b3ca7cee46c83f32443c36632` assumes the historical Tarot hex.
Issue #16 is the calibration mission for that platform, not a Plane survey
adapter. Existing open issues and all 15 branches were reviewed on 2026-10-10.

Extend the existing planner connection; do not build a separate survey UI.

- Accept a versioned design handoff with aircraft identity, achieved endurance
  for the selected pack/payload, reserve policy, stall/survey/airspeed bounds,
  bank/turn constraints, camera footprint/trigger/exposure limits and source hashes.
  Distinguish a 50-minute design target from verified/estimated usable flight time.
- Add ArduPilot Plane plan parsing and mission-index/endpoint association using
  real QGC/Mission Planner saved fixtures. Keep current PX4 validation behavior.
- Check minimum safe airspeed and maximum camera groundspeed independently with
  the stated wind bound. At the present nominal 100 m/25 mm/2.74 µm camera geometry,
  0.4 ms exposure and 0.6 px blur give 16.44 m/s maximum groundspeed. A tailwind
  can make the camera and aircraft constraints incompatible; refuse that case.
- Model fixed-wing turnaround radius, boundary/geofence crossings along paths,
  terrain-relative height, climb/transit/turn/return time and battery reserve;
  unsupported mission items or absent wind/terrain assumptions remain explicit.
- Bind the checked plan and active hardware/camera/calibration profile hashes to
  recording and product provenance. Changing camera or pack invalidates the check.
- Keep plan generation/checking offline. Upload/arming and persistent autopilot
  parameters stay deliberate operator operations; capture uses the existing link.

Acceptance:

1. Existing PX4/OAK fixtures continue to pass and unsupported vehicles still fail.
2. Plane fixtures prove item numbering, takeoff/landing/abort, mission restart,
   wind/airspeed vs blur conflict, insufficient turn radius, terrain/altitude frame
   mismatch, unsafe path segments and stale profile-hash rejection.
3. ArduPilot Plane SITL runs the reviewed plan and verifies recording/leg endpoints
   and abort behavior without touching physical hardware. PX4 SIH failure work
   in PR #24 remains independently tracked.
4. The exported camera definition derives the actual selected SKU, dimensions,
   nominal intrinsics and requested FPS; it is not accepted as measured calibration.
5. A subsequent operator-reviewed real flight links the identical checked plan,
   session and derived products. That physical acceptance is reported separately.

Design-side implementation: `uavdesign.integration`, `integration/mapping_profile.yaml`,
`integration/handoff.schema.json`, `docs/software_spec.md` in
`WalleringRobotics/UAV_Design_Environment`.
