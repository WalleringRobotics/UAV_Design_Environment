"""Component-level mass rollup with contingency, sensitivity and balance helpers.

Shared by every platform. Components may optionally carry a longitudinal
position (``x_mm``, measured aft from a platform-defined datum — the wing root
leading edge for the flying wing). Positions are only required when a CG is
requested, so multirotor budgets can stay mass-only.
"""

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
    positions_mm: dict[str, float] = field(default_factory=dict)

    # ---- I/O ---------------------------------------------------------------

    @classmethod
    def from_yaml(
        cls,
        airframe_yaml: str | Path,
        payload_yaml: str | Path | None = None,
        active_payloads: list[str] | None = None,
        extra_components_g: dict[str, float] | None = None,
        include_always_on: bool = True,
        payload_positions_mm: dict[str, float] | None = None,
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
        include_always_on : bool
            Add manifest entries flagged ``always_on``. Platforms that cannot
            carry the multirotor's always-on stack (e.g. a sub-kg wing) set
            this False and list what they carry in ``active_payloads``.
        payload_positions_mm : dict, optional
            x positions for payload names, keyed by manifest name.

        Entries under ``fixed_components_g`` may be a bare mass in grams or a
        mapping ``{mass_g: ..., x_mm: ...}``.
        """
        with open(airframe_yaml) as f:
            air = yaml.safe_load(f)

        components: dict[str, float] = {}
        positions: dict[str, float] = {}
        for name, spec in (air.get("fixed_components_g") or {}).items():
            if isinstance(spec, dict):
                components[name] = float(spec["mass_g"])
                if spec.get("x_mm") is not None:
                    positions[name] = float(spec["x_mm"])
            else:
                components[name] = float(spec)
        contingency = float(air.get("contingency_fraction", 0.08))
        payload_positions_mm = payload_positions_mm or {}

        if payload_yaml is not None:
            with open(payload_yaml) as f:
                pay = yaml.safe_load(f)
            payloads = pay.get("payloads", {})
            active = set(active_payloads or [])
            unknown = active - set(payloads)
            if unknown:
                raise KeyError(f"Payloads not in manifest: {sorted(unknown)}")
            for name, spec in payloads.items():
                if (include_always_on and spec.get("always_on")) or name in active:
                    key = f"payload:{name}"
                    components[key] = float(spec["mass_g"])
                    if name in payload_positions_mm:
                        positions[key] = float(payload_positions_mm[name])

        if extra_components_g:
            for name, mass_g in extra_components_g.items():
                components[name] = float(mass_g)

        return cls(
            components_g=components,
            contingency_fraction=contingency,
            positions_mm=positions,
        )

    # ---- Mutation ----------------------------------------------------------

    def add(self, name: str, mass_g: float, x_mm: float | None = None) -> None:
        self.components_g[name] = float(mass_g)
        if x_mm is not None:
            self.positions_mm[name] = float(x_mm)

    def set_position(self, name: str, x_mm: float) -> None:
        if name not in self.components_g:
            raise KeyError(name)
        self.positions_mm[name] = float(x_mm)

    def remove(self, name: str) -> None:
        self.components_g.pop(name, None)
        self.positions_mm.pop(name, None)

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

    # ---- Balance -----------------------------------------------------------
    #
    # Contingency mass is unallocated, so it is assumed to sit at the CG of the
    # known components: it changes AUW but not the CG location.

    def _missing_positions(self) -> list[str]:
        return [n for n in self.components_g if n not in self.positions_mm]

    def cg_x_mm(self) -> float:
        """Longitudinal CG (mm from datum) of the positioned components."""
        missing = self._missing_positions()
        if missing:
            raise ValueError(f"No x_mm for components: {missing}")
        m = self.dry_mass_g
        if m <= 0:
            raise ValueError("Empty budget has no CG")
        return sum(self.components_g[n] * self.positions_mm[n] for n in self.components_g) / m

    def solve_position_for_cg(self, name: str, target_cg_x_mm: float) -> float:
        """x position for component `name` that puts the CG on `target_cg_x_mm`.

        The classic flying-wing use: slide the battery fore/aft until the
        static margin is right, then check that the answer fits in the pod.
        Does not modify the budget.
        """
        if name not in self.components_g:
            raise KeyError(name)
        others = [n for n in self.components_g if n != name]
        missing = [n for n in others if n not in self.positions_mm]
        if missing:
            raise ValueError(f"No x_mm for components: {missing}")
        m_item = self.components_g[name]
        if m_item <= 0:
            raise ValueError(f"{name!r} has no mass to move")
        moment_others = sum(self.components_g[n] * self.positions_mm[n] for n in others)
        return (target_cg_x_mm * self.dry_mass_g - moment_others) / m_item
