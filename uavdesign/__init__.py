"""Wallering Robotics UAV design environment — shared sizing models.

Platform-agnostic modules (used by every platform under ``platforms/``):

* :mod:`uavdesign.atmosphere` — ISA density, unit helpers
* :mod:`uavdesign.mass`       — mass budget, contingency, tornado, CG/balance
* :mod:`uavdesign.power`      — avionics + payload multi-rail power budget
* :mod:`uavdesign.endurance`  — battery, Peukert, mission-segment energy
* :mod:`uavdesign.propulsion` — rotor (hover) and propeller (cruise) power,
  shaft -> electrical conversion

Fixed-wing specific:

* :mod:`uavdesign.aero` — wing geometry/MAC/static margin, drag polar,
  constraint analysis
* :mod:`uavdesign.survey`, :mod:`uavdesign.payload` — imaging and sensor budgets
* :mod:`uavdesign.sizing`, :mod:`uavdesign.design` — coupled design closure
* :mod:`uavdesign.electronics`, :mod:`uavdesign.structures` — component checks
* :mod:`uavdesign.fab` — optional CAD, print fit and calibration (lazy import)
* :mod:`uavdesign.integration`, :mod:`uavdesign.artifacts` — review exports

All quantities are SI unless the variable name says otherwise (wing geometry
is in mm, matching how small planforms are drawn).
"""

from . import aero, atmosphere, endurance, mass, power, propulsion

__all__ = ["aero", "atmosphere", "endurance", "mass", "power", "propulsion"]
