# Add camera capability profiles and GigE/event/PPK ingestion for the new survey wing

The existing OAK-D/PX4 hardware and its ROS/MCAP recording path must remain supported.
`WalleringRobotics/UAV_Design_Environment` now also designs a dedicated ArduPilot
survey wing: rigid camera/F9P cage, independent flight GNSS, Orin or CM5. Basler
is the preferred camera candidate, not mandatory. The current design selects the
IMX542-class a2A5320-7gcPRO/25 mm lens; substitute cameras should satisfy the same
declared geometry, timing, throughput and calibration requirements.

Inspected main: `51a3d3237cd6033146b8d0d472d4ff15c1c68dc6`.
`docs/architecture.md` binds acquisition to OAK CAM_A/B/C; `rig_calibration.py`
restricts frame names and clock pairs to OAK/PX4. `docs/roadmap.md` identifies
GigE/GenICam and survey event marks as future work. PRs #24–#26 do not add these
adapters. Existing #6–#18 cover the OAK implementation and qualification; this
request is additive platform support, not duplicate OAK calibration work.

Scope:

- Introduce versioned camera/rig capability profiles and adapter boundaries while
  retaining the current OAK defaults, fixtures and immutable dataset semantics.
- Add an initial vendor-supported GigE acquisition path with exact SKU/pixel mode,
  native frame counters, chunk timestamp clock domain, requested/effective settings,
  calibration/firmware identity, packet-loss diagnostics and lossless raw evidence.
- Preserve independent F9P RAWX/SFRBX/TIM-TM2 and trigger/ExposureActive evidence.
  Associate by explicit counters/edges, retain unmatched records, characterize
  edge polarity/delays, and distinguish exposure midpoint from host receipt time.
- Generalize frames and clock bridges with uncertainty. Include antenna ARP,
  optical centre, CAD datum conversion and isolated-cage motion limitations;
  never label design-envelope positions as measured calibration.
- Consume the versioned design handoff emitted by `uavdesign.integration`, seal its
  source/profile hashes into the session, and audit link/storage/thermal budgets.
  The 4 fps acquisition target is separate from camera maximum FPS. Unpacked
  16-bit ~16 MP data at 4 fps exceeds 1 Gb/s; reject incompatible modes explicitly.
- Preserve offline export/COLMAP/ODM and the pending PR #24 OpenSfM path. Orin
  live mosaic remains optional future work; CM5 must support capture-only.

Acceptance:

1. All existing OAK/PX4 tests pass without hardware/config migration.
2. Pure software tests cover camera counter reset/wrap, missing/duplicate event
   edges, clock resets, GNSS week/time-system handling, ambiguity refusal,
   backpressure, full disk and interrupted sealing; originals remain immutable.
3. One real chosen-camera sample imports into the existing processing contract
   with exact calibration/pixel provenance; unsupported modes fail clearly.
4. Each chosen compute/carrier/storage combination passes a full requested-window
   soak with hardware continuity evidence, thermal/load/write-rate metrics and
   controlled fault/stop behavior. Fixture success alone does not meet this gate.
5. Real event/optical timing and measured rigid-cage calibration retain independent
   uncertainties. Georeferencing stays unqualified until these are evidenced.

Related design artifacts: `integration/handoff.schema.json`, generated
`mapping_handoff.json`, `docs/software_spec.md` in the design repository.
