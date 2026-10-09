"""Multi-rail power budget for the airframe avionics + payload."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Consumer:
    """A single load on a power rail."""

    name: str
    rail: str
    idle_a: float
    peak_a: float
    duty_cycle: float = 1.0  # average fraction of time at peak in cruise/hover

    @property
    def average_a(self) -> float:
        return self.idle_a + self.duty_cycle * (self.peak_a - self.idle_a)


@dataclass
class Rail:
    """A regulated bus that supplies one or more consumers."""

    name: str
    voltage_v: float
    capacity_a: float | None = None  # None means "main pack, not a regulator"


@dataclass
class PowerBudget:
    """Bookkeeping for total current draw across rails.

    Note: the propulsion bus (motors + ESCs) is modelled separately by the
    propulsion notebook; this class targets avionics + payload rails.
    """

    rails: dict[str, Rail] = field(default_factory=dict)
    consumers: list[Consumer] = field(default_factory=list)

    def add_rail(self, name: str, voltage_v: float, capacity_a: float | None = None) -> None:
        self.rails[name] = Rail(name=name, voltage_v=voltage_v, capacity_a=capacity_a)

    def add_consumer(
        self,
        name: str,
        rail: str,
        idle_a: float,
        peak_a: float,
        duty_cycle: float = 1.0,
    ) -> None:
        if rail not in self.rails:
            raise KeyError(f"Rail {rail!r} not registered; call add_rail first.")
        self.consumers.append(Consumer(name, rail, idle_a, peak_a, duty_cycle))

    # ---- Rollups -----------------------------------------------------------

    def rail_totals(self) -> dict[str, dict[str, float]]:
        """Per-rail current and power totals.

        Returns a dict keyed by rail name with idle_a, peak_a, average_a, average_w.
        """
        out: dict[str, dict[str, float]] = {
            name: {"idle_a": 0.0, "peak_a": 0.0, "average_a": 0.0}
            for name in self.rails
        }
        for c in self.consumers:
            r = out[c.rail]
            r["idle_a"] += c.idle_a
            r["peak_a"] += c.peak_a
            r["average_a"] += c.average_a
        for name, r in out.items():
            r["average_w"] = r["average_a"] * self.rails[name].voltage_v
            r["peak_w"] = r["peak_a"] * self.rails[name].voltage_v
        return out

    def total_average_w(self) -> float:
        return sum(r["average_w"] for r in self.rail_totals().values())

    def bec_recommendation(self, headroom: float = 0.20) -> dict[str, float]:
        """Suggest a continuous BEC/UBEC current rating per regulated rail.

        Skips the main propulsion pack (capacity_a is None).
        """
        recs: dict[str, float] = {}
        for name, totals in self.rail_totals().items():
            if self.rails[name].capacity_a is None:
                continue
            recs[name] = totals["peak_a"] * (1.0 + headroom)
        return recs

    def warnings(self) -> list[str]:
        """Flag rails whose peak draw exceeds declared capacity."""
        msgs: list[str] = []
        for name, totals in self.rail_totals().items():
            cap = self.rails[name].capacity_a
            if cap is not None and totals["peak_a"] > cap:
                msgs.append(
                    f"Rail {name!r}: peak {totals['peak_a']:.2f} A exceeds capacity {cap:.2f} A"
                )
        return msgs
