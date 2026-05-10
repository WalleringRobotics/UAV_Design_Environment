"""Component-level mass rollup with contingency factor and sensitivity helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class MassBudget:
    """Bottom-up component mass budget.

    All component masses are stored in grams; AUW is exposed in both g and kg.
    """

    components_g: dict[str, float] = field(default_factory=dict)
    contingency_fraction: float = 0.08

    # ---- I/O ---------------------------------------------------------------

    @classmethod
    def from_yaml(
        cls,
        airframe_yaml: str | Path,
        payload_yaml: str | Path | None = None,
        active_payloads: list[str] | None = None,
        extra_components_g: dict[str, float] | None = None,
    ) -> "MassBudget":
        """Build a budget from the airframe + optional payload YAML.

        Parameters
        ----------
        airframe_yaml : path
            File holding `fixed_components_g` and `contingency_fraction`.
        payload_yaml : path, optional
            File holding the payload manifest. If provided, `always_on` payloads
            and any names in `active_payloads` are added.
        active_payloads : list[str], optional
            Names of swap-bay payloads to include alongside the always-on set.
        extra_components_g : dict, optional
            Extra parametric items (motors, ESCs, props, battery, ...).
        """
        with open(airframe_yaml) as f:
            air = yaml.safe_load(f)

        components: dict[str, float] = dict(air.get("fixed_components_g", {}))
        contingency = float(air.get("contingency_fraction", 0.08))

        if payload_yaml is not None:
            with open(payload_yaml) as f:
                pay = yaml.safe_load(f)
            payloads = pay.get("payloads", {})
            active = set(active_payloads or [])
            for name, spec in payloads.items():
                if spec.get("always_on") or name in active:
                    components[f"payload:{name}"] = float(spec["mass_g"])

        if extra_components_g:
            for name, mass_g in extra_components_g.items():
                components[name] = float(mass_g)

        return cls(components_g=components, contingency_fraction=contingency)

    # ---- Mutation ----------------------------------------------------------

    def add(self, name: str, mass_g: float) -> None:
        self.components_g[name] = float(mass_g)

    def remove(self, name: str) -> None:
        self.components_g.pop(name, None)

    # ---- Rollup ------------------------------------------------------------

    @property
    def dry_mass_g(self) -> float:
        """Sum of components before contingency."""
        return sum(self.components_g.values())

    @property
    def contingency_mass_g(self) -> float:
        return self.dry_mass_g * self.contingency_fraction

    @property
    def auw_g(self) -> float:
        return self.dry_mass_g + self.contingency_mass_g

    @property
    def auw_kg(self) -> float:
        return self.auw_g / 1000.0

    def as_table(self) -> list[tuple[str, float, float]]:
        """List of (name, mass_g, fraction_of_auw) sorted descending by mass."""
        total = self.auw_g if self.auw_g > 0 else 1.0
        rows = [(n, m, m / total) for n, m in self.components_g.items()]
        rows.append(("contingency", self.contingency_mass_g, self.contingency_mass_g / total))
        rows.sort(key=lambda r: r[1], reverse=True)
        return rows

    # ---- Sensitivity -------------------------------------------------------

    def tornado(self, fraction: float = 0.10) -> list[tuple[str, float, float]]:
        """Per-component AUW sensitivity to a +/- `fraction` perturbation.

        Returns list of (name, low_auw_kg, high_auw_kg).
        """
        baseline = self.auw_kg
        rows: list[tuple[str, float, float]] = []
        for name, mass_g in self.components_g.items():
            delta_g = mass_g * fraction
            low = (self.dry_mass_g - delta_g) * (1 + self.contingency_fraction) / 1000.0
            high = (self.dry_mass_g + delta_g) * (1 + self.contingency_fraction) / 1000.0
            rows.append((name, low, high))
        rows.sort(key=lambda r: abs(r[2] - r[1]), reverse=True)
        # Sanity: baseline used for documentation by the caller.
        _ = baseline
        return rows
