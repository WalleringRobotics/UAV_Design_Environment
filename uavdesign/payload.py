"""Survey payload (cage + tray + compute) bookkeeping.

Reads ``payload/survey_cage.yaml`` and rolls a chosen compute configuration up
into mass, power and the cage's own centre of gravity (in cage coordinates).
Platform code places the cage in the airframe; this module never knows where.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml


@dataclass
class SurveyPayload:
    config: str
    cage_members: dict
    cage_structure_mass_g: float
    tray: dict
    compute: dict
    window_standoff_mm: float
    damper_count: int

    @classmethod
    def from_yaml(cls, path: str | Path, config: str, cage_structure_g: float | None = None) -> "SurveyPayload":
        spec = yaml.safe_load(Path(path).read_text())
        if config not in spec["compute"]:
            raise KeyError(f"unknown compute config {config!r}; have {list(spec['compute'])}")
        cage = spec["cage"]
        return cls(
            config=config,
            cage_members=cage["members"],
            cage_structure_mass_g=float(cage_structure_g if cage_structure_g is not None else cage["structure_mass_g"]),
            tray=spec.get("tray", {}),
            compute=spec["compute"][config],
            window_standoff_mm=float(cage.get("window_standoff_mm", 5.0)),
            damper_count=int(cage.get("damper_count", 4)),
        )

    # ---- mass ---------------------------------------------------------------

    @property
    def cage_mass_g(self) -> float:
        """Everything on the isolated cage, including its printed structure."""
        return self.cage_structure_mass_g + sum(m["mass_g"] for m in self.cage_members.values())

    @property
    def tray_mass_g(self) -> float:
        return sum(t["mass_g"] for t in self.tray.values()) + self.compute["mass_g"]

    @property
    def mass_g(self) -> float:
        return self.cage_mass_g + self.tray_mass_g

    @property
    def mass_kg(self) -> float:
        return self.mass_g / 1000.0

    # ---- power --------------------------------------------------------------

    @property
    def power_w(self) -> float:
        p = sum(m.get("power_w", 0.0) for m in self.cage_members.values())
        p += sum(t.get("power_w", 0.0) for t in self.tray.values())
        return p + self.compute.get("power_w", 0.0)

    # ---- geometry -----------------------------------------------------------

    def cage_cg_mm(self, structure_cg_mm=(0.0, 0.0, 70.0)) -> np.ndarray:
        """CG of the cage assembly in cage coordinates.

        Member positions are envelope base centres; their CG is taken at half
        the envelope height above that.
        """
        m_tot, mom = 0.0, np.zeros(3)
        for mem in self.cage_members.values():
            p = np.asarray(mem["position_mm"], float) + [0, 0, mem["envelope_mm"][2] / 2]
            mom += mem["mass_g"] * p
            m_tot += mem["mass_g"]
        mom += self.cage_structure_mass_g * np.asarray(structure_cg_mm, float)
        m_tot += self.cage_structure_mass_g
        return mom / m_tot

    @property
    def cage_height_mm(self) -> float:
        """Lens front face to the top of the highest cage member."""
        return max(m["position_mm"][2] + m["envelope_mm"][2] for m in self.cage_members.values())

    def summary(self) -> dict:
        return {
            "config": self.config,
            "label": self.compute.get("label", self.config),
            "cage_mass_g": self.cage_mass_g,
            "tray_mass_g": self.tray_mass_g,
            "payload_mass_g": self.mass_g,
            "payload_power_w": self.power_w,
            "cage_height_mm": self.cage_height_mm,
        }
