"""Wallering Robotics UAV design environment — shared sizing models.

Platform-agnostic modules (used by every platform under ``platforms/``):

* :mod:`uavdesign.atmosphere` — ISA density, unit helpers
* :mod:`uavdesign.mass`       — mass budget, contingency, tornado, CG/balance
* :mod:`uavdesign.power`      — avionics + payload multi-rail power budget
* :mod:`uavdesign.endurance`  — battery, Peukert, mission-segment energy
* :mod:`uavdesign.propulsion` — rotor (hover) and propeller (cruise) power,
  shaft -> electrical conversion

All quantities are SI unless the variable name says otherwise.
"""

from . import atmosphere, endurance, mass, power, propulsion

__all__ = ["atmosphere", "endurance", "mass", "power", "propulsion"]
