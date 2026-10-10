# Design takeover review — 10 October 2026

The notebook-first plan was a useful scaffold but was not a deliverable pipeline.
The latest branch contains the more relevant survey-wing design and fabrication
work. This iteration uses that as its baseline and produces a versioned review
package: CAD, BOM, dedicated hardware specification and a mapping-software
handoff. A generated file is complete as a review artifact; it does not establish
that a physical aircraft is ready to build or fly.

## Branch reconciliation

All remote heads were checked against GitHub on 10 October 2026 and incorporated
into local branch `codex/artifact-delivery` without conflicts:

| Branch | Inspected tip | Disposition |
|---|---|---|
| main | 79243a1 | Ancestor of both feature branches |
| claude/commit-spec-build-edR6B | 7125287 | Original checkout; review fixes retained |
| feature/flying-wing-platform | aad2f9c | Included through survey-wing descendant |
| feature/survey-wing-fabrication | 8080421 | Primary implementation baseline |
| base-spec-only | 2c4c204 | Merge history incorporated; no additional content |

The adjacent mapping repository has three distinct, unmerged work streams:
OpenSfM runtime (#24), first-flight documentation (#25), and QGC survey planning
(#26). Its branch audit is recorded in the software specification. Those are
separate changes for the existing platform; local reconciliation here does not
claim to have merged or validated them remotely.

## Findings and response

| Priority | Finding | Engineering response |
|---|---|---|
| Critical | Calibration could be saved after iteration exhaustion and without AUW agreement. | Fail on nonconvergence; test exhaustion and preserve prior calibration; require stable wing/pod/cage factors and <1% sizing/balance disagreement. Save the inputs actually built. |
| Critical | Battery CG bounds did not prove physical pack fit. | Use explicit bay envelopes and retained trays; report attainable CG instead of assuming an unconstrained balance solution. |
| High | Basler a2A5328-4gcPRO was incorrectly described as IMX542/16MP. | Preferred candidate corrected to a2A5320-7gcPRO; payload mass/envelope and imaging parameters updated from manufacturer. |
| High | Software assumptions conflated an existing OAK/PX4 aircraft with the new fixed wing. | Preserve existing workflow; add distinct fixed-wing hardware/camera profiles and capability requirements. |
| High | USB camera/receiver/datalink loads could disappear from pack power; peak currents were absent. | Propagate downstream loads and conversion losses; distinguish typical power from peak assumptions and missing vendor evidence. |
| High | CAD had retention and mating-feature omissions. | Add features and geometry checks; export only valid connected parts that fit the configured printer. |
| High | Endurance and launch calculations overstated evidence. | Treat CT/CP, aerodynamic polars and printed masses as estimates; expose assumptions and selected-hardware limitations. |
| High | The provisional 40 A ESC failed the modeled full-voltage load plus headroom. | Select a documented 60 A Talon candidate, carry its 57 g mass into sizing, and read the rating directly from the electronics BOM. Cooling and measured current remain qualification items. |
| Medium | Survey notebooks described in README did not exist. | Add generated, executable notebooks covering the complete design chain. |
| Medium | Loose dependency versions and loose files weakened reproducibility. | Export dependency versions, source/input hashes, manifests, a clean directory and a ZIP. |

The original multirotor notebooks still represent separate conceptual trade
studies. They are retained for the existing design history; the release builder
and dedicated hardware specification describe the new survey wing.

## Decisions and evidence still required

Hand launch remains selected. A bungee option is a quantified alternative, not
an implicit change of mission. Orin and CM5 are alternative compute loads on the
same aircraft. Basler is preferred but replaceable by a camera that satisfies
the same lens, imaging, synchronization and capture-throughput requirements.

Confirm ESC installation and cooling, motor mass, folding hub/blade geometry, receiver, airspeed
breakout, regulator SKU, camera stock, carrier and heatsink. Do not equate brand
country with component manufacturing origin. Existing upstream `verified` flags
are retained as provenance, not evidence of fresh verification of every item.
Quotes and supplier stock are deliberately not invented.

Printed mass is a surface/infill estimate, not slicer output or a scale reading.
Analytic envelope checks cannot validate connectors, flexible leads, screw
access, print shrinkage, layer adhesion or assembly tolerances. NeuralFoil/VLM
estimates require aerodynamic validation; the simple static prop model requires
a thrust stand. Deployed prop clearance does not prove folded-blade clearance.
Mission endurance needs takeoff/climb/turn/landing and real battery-discharge
evidence before becoming an operational promise.

## Manufacturer evidence

- [Correct IMX542 Basler candidate](https://www.baslerweb.com/en/shop/a2a5320-7gcpro/): 5320×3032, 7 fps, global shutter, 2.74 µm pixels, 105 g, 55.5×29×29 mm, typical 3.4 W.
- [Previously listed IMX540 SKU](https://www.baslerweb.com/en/shop/a2a5328-4gcpro/): different sensor and image format; it must not inherit the IMX542 calibration.
- [Allied Vision alternative datasheet](https://www.alliedvision.com/assets/support/Camera-Documentation/Allied-Vision/Cameras/Alvium/Alvium-G1/Data-Sheets/Alvium_G1-1620_DataSheet_en.pdf): G1-1620 uses IMX542, 5328×3040, 7.3 fps at Mono8. Colour pixel format, timing I/O and integration need qualification before substitution.
