"""Electronics bill of materials, battery pack and power tree.

Reads ``platforms/<platform>/electronics.yaml``. Provides the avionics mass
and power that the sizing closure needs, the selected propulsion masses, the
discrete battery pack, and a rail-by-rail power tree (with regulator losses
propagated back to the pack) for the wiring and BEC checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Pack:
    series: int
    parallel: int
    cell_mass_g: float
    cell_capacity_ah: float
    cell_nominal_v: float
    cell_min_v: float
    cell_max_v: float
    overhead_fraction: float

    @classmethod
    def from_dict(cls, d: dict) -> "Pack":
        return cls(int(d["series"]), int(d["parallel"]), float(d["cell_mass_g"]),
                   float(d["cell_capacity_ah"]), float(d["cell_nominal_v"]),
                   float(d["cell_min_v"]), float(d["cell_max_v"]), float(d["overhead_fraction"]))

    def with_parallel(self, p: int) -> "Pack":
        return Pack(self.series, p, self.cell_mass_g, self.cell_capacity_ah, self.cell_nominal_v,
                    self.cell_min_v, self.cell_max_v, self.overhead_fraction)

    @property
    def cells(self) -> int:
        return self.series * self.parallel

    @property
    def capacity_ah(self) -> float:
        return self.cell_capacity_ah * self.parallel

    @property
    def nominal_v(self) -> float:
        return self.cell_nominal_v * self.series

    @property
    def min_v(self) -> float:
        return self.cell_min_v * self.series

    @property
    def max_v(self) -> float:
        return self.cell_max_v * self.series

    @property
    def energy_wh(self) -> float:
        return self.capacity_ah * self.nominal_v

    @property
    def mass_g(self) -> float:
        return self.cells * self.cell_mass_g * (1.0 + self.overhead_fraction)

    @property
    def label(self) -> str:
        return f"{self.series}S{self.parallel}P"


class Electronics:
    def __init__(self, spec: dict):
        self.spec = spec
        self.components: dict = spec["components"]
        self.pack = Pack.from_dict(spec["pack"])
        self.rails: dict = spec["rails"]
        self.payload_rails: dict = spec.get("payload_rails", {})

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Electronics":
        return cls(yaml.safe_load(Path(path).read_text()))

    # ---- mass ---------------------------------------------------------------

    def group_mass_g(self, group: str) -> float:
        return sum(c["qty"] * c["mass_g"] for c in self.components.values() if c.get("group") == group)

    @property
    def avionics_mass_g(self) -> float:
        """Everything that is neither propulsion nor the pack."""
        return self.group_mass_g("avionics") + self.group_mass_g("power")

    @property
    def propulsion_masses_g(self) -> dict:
        c = self.components
        return {
            "motor": c["motor"]["qty"] * c["motor"]["mass_g"],
            "esc": c["esc"]["qty"] * c["esc"]["mass_g"],
            "prop_spinner": c["propeller"]["qty"] * c["propeller"]["mass_g"],
        }

    # ---- power --------------------------------------------------------------

    @property
    def avionics_power_w(self) -> float:
        return sum(c["qty"] * c.get("power_w", 0.0) for c in self.components.values()
                   if c.get("group") == "avionics")

    # Efficiencies of the converters that are not separate BOM items
    SOURCE_EFFICIENCY = {"flight_controller": 0.85}

    def power_tree(self, payload_loads_w: dict) -> dict:
        """Per-rail power, bottom-up, with conversion losses propagated to the pack.

        Each rail's ``from`` is the battery, a regulator in the BOM (uses its
        ``efficiency``), the FC / power-monitor BEC (fixed efficiencies), or
        ``compute`` (USB devices — already inside the computer's rated draw,
        so not propagated). Returns {rail: {direct_w, total_w, current_a,
        capacity_a, utilisation}} and 'pack_total_w' (avionics + payload,
        excluding propulsion).
        """
        direct = {r: 0.0 for r in self.rails}
        for c in self.components.values():
            r = c.get("rail")
            if r in direct:
                direct[r] += c["qty"] * c.get("power_w", 0.0)
        for name, w in payload_loads_w.items():
            r = self.payload_rails.get(name)
            if r is None:
                raise KeyError(f"payload item {name!r} has no rail in payload_rails")
            direct[r] += w

        regulators = {c["feeds"]: c for c in self.components.values() if c.get("feeds")}
        parent = {}
        for r, spec in self.rails.items():
            src = spec["from"]
            if src == "battery":
                continue
            if r in regulators:
                parent[r] = ("pack", regulators[r].get("efficiency", 0.9))
            elif src == "flight_controller":
                # the FC's onboard regulators run straight off the pack
                parent[r] = ("pack", self.SOURCE_EFFICIENCY["flight_controller"])
            # 'compute' and 'pack'-fed rails (ESC) do not propagate here

        total = dict(direct)

        def depth(r):
            return 0 if r not in parent else 1 + depth(parent[r][0])

        for r in sorted(parent, key=depth, reverse=True):
            up, eff = parent[r]
            total[up] += total[r] / eff

        out = {}
        for r, spec in self.rails.items():
            v = spec["voltage_nominal_v"]
            cap = spec.get("capacity_a")
            a = total[r] / v if v else 0.0
            out[r] = {"direct_w": direct[r], "total_w": total[r], "current_a": a,
                      "capacity_a": cap, "utilisation": (a / cap) if cap else None}
        out["pack_total_w"] = total["pack"] - direct["esc"] if "esc" in direct else total["pack"]
        return out

    # ---- reporting ----------------------------------------------------------

    def bom_rows(self) -> list[dict]:
        rows = []
        for key, c in self.components.items():
            rows.append({
                "item": key,
                "part": c["part"],
                "qty": c["qty"],
                "mass_g": c["qty"] * c["mass_g"],
                "group": c.get("group", ""),
                "provenance": c.get("provenance", ""),
                "verified": bool(c.get("verified", False)),
                "confirm": c.get("confirm", ""),
            })
        return rows

    def open_items(self) -> list[str]:
        return [f"{k}: {c['confirm']}" for k, c in self.components.items() if c.get("confirm")]
