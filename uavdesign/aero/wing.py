"""Wing planform geometry, MAC, neutral point and static margin.

Coordinates
-----------
* ``x`` — chordwise, positive aft, measured from the **wing root leading edge**.
* ``y`` — spanwise, positive outboard, measured from the centreline.

All lengths are in millimetres, matching how RC/small-UAS planforms are
drawn and how the rcplanes.online flying-wing CG calculator is fed. Areas are
reported in mm^2, with m^2 / dm^2 helpers for the performance models.

Model
-----
A half-wing is a list of straight-tapered :class:`Panel` objects joined
end-to-end (one panel = plain trapezoid; two = cranked wing). For each panel
the closed-form trapezoid results are exact:

    MAC     = 2/3 * (cr + ct - cr*ct / (cr + ct))
    y_mac   = b/3 * (cr + 2 ct) / (cr + ct)
    x_le    = sweep_le * y_mac / b

and for the whole wing every quantity is an exact panel-area-weighted sum,
because MAC * area = integral of c^2 dy and x_le,mac * area = integral of
c * x_le dy. Splitting a trapezoid into two coplanar panels therefore gives
identical answers (this is checked in the tests).

The aerodynamic centre is estimated at a fixed fraction of the MAC (25 % by
default). For a tailless aircraft this AC *is* the neutral point, so

    static margin  SM = (x_np - x_cg) / MAC
    target CG      x_cg = x_np - SM * MAC

This is the same first-order model the online calculator uses. It ignores
the aft shift of the AC with sweep/compressibility and the fuselage pod's
destabilising contribution — both small for a slow foam wing, but the
static margin you pick should cover them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

_trapz = getattr(np, "trapezoid", None) or np.trapz  # numpy 1.x / 2.x


@dataclass(frozen=True)
class Panel:
    """One straight-tapered panel of the half-wing.

    Parameters
    ----------
    root_chord_mm, tip_chord_mm : float
        Chords at the inboard and outboard ends of the panel.
    span_mm : float
        Spanwise length of the panel (one side).
    le_sweep_mm : float
        Aft displacement of the leading edge from panel root to panel tip.
    root_y_mm, root_le_x_mm : float
        Where the panel root sits; filled in automatically by :class:`Wing`.
    """

    root_chord_mm: float
    tip_chord_mm: float
    span_mm: float
    le_sweep_mm: float = 0.0
    root_y_mm: float = 0.0
    root_le_x_mm: float = 0.0

    def __post_init__(self) -> None:
        if self.root_chord_mm <= 0 or self.tip_chord_mm < 0:
            raise ValueError("chords must be positive (tip may be 0 for a pointed tip)")
        if self.span_mm <= 0:
            raise ValueError("span_mm must be positive")

    # ---- panel-local closed forms -----------------------------------------

    @property
    def area_mm2(self) -> float:
        """Planform area of this panel on one side."""
        return 0.5 * (self.root_chord_mm + self.tip_chord_mm) * self.span_mm

    @property
    def taper_ratio(self) -> float:
        return self.tip_chord_mm / self.root_chord_mm

    @property
    def mac_mm(self) -> float:
        cr, ct = self.root_chord_mm, self.tip_chord_mm
        return (2.0 / 3.0) * (cr + ct - cr * ct / (cr + ct))

    @property
    def y_mac_local_mm(self) -> float:
        cr, ct = self.root_chord_mm, self.tip_chord_mm
        return self.span_mm / 3.0 * (cr + 2.0 * ct) / (cr + ct)

    @property
    def y_mac_mm(self) -> float:
        return self.root_y_mm + self.y_mac_local_mm

    @property
    def x_le_mac_mm(self) -> float:
        return self.root_le_x_mm + self.le_sweep_mm * self.y_mac_local_mm / self.span_mm

    @property
    def le_sweep_deg(self) -> float:
        return math.degrees(math.atan2(self.le_sweep_mm, self.span_mm))

    def sweep_deg_at(self, chord_fraction: float) -> float:
        """Sweep angle of the line at `chord_fraction` (0 = LE, 0.25 = c/4, 1 = TE)."""
        dx = self.le_sweep_mm + chord_fraction * (self.tip_chord_mm - self.root_chord_mm)
        return math.degrees(math.atan2(dx, self.span_mm))

    @property
    def tip_y_mm(self) -> float:
        return self.root_y_mm + self.span_mm

    @property
    def tip_le_x_mm(self) -> float:
        return self.root_le_x_mm + self.le_sweep_mm


@dataclass
class Wing:
    """A symmetric wing built from one or more panels per side.

    Parameters
    ----------
    panels : list[Panel]
        Inboard to outboard. Each panel's root chord should equal the previous
        panel's tip chord (checked); its root position is placed automatically.
    ac_chord_fraction : float
        Aerodynamic-centre location as a fraction of MAC (0.25 default).
    """

    panels: list[Panel]
    ac_chord_fraction: float = 0.25
    _placed: list[Panel] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.panels:
            raise ValueError("a wing needs at least one panel")
        placed: list[Panel] = []
        y, x = 0.0, 0.0
        prev_tip = None
        for p in self.panels:
            if prev_tip is not None and not math.isclose(p.root_chord_mm, prev_tip, rel_tol=1e-6):
                raise ValueError(
                    f"panel root chord {p.root_chord_mm} != previous tip chord {prev_tip}"
                )
            placed.append(
                Panel(p.root_chord_mm, p.tip_chord_mm, p.span_mm, p.le_sweep_mm, y, x)
            )
            y += p.span_mm
            x += p.le_sweep_mm
            prev_tip = p.tip_chord_mm
        self._placed = placed

    # ---- constructors ------------------------------------------------------

    @classmethod
    def trapezoidal(
        cls,
        root_chord_mm: float,
        tip_chord_mm: float,
        half_span_mm: float,
        le_sweep_mm: float | None = None,
        le_sweep_deg: float | None = None,
        ac_chord_fraction: float = 0.25,
    ) -> "Wing":
        """Single-panel wing. Give the sweep as a distance *or* an angle."""
        if (le_sweep_mm is None) == (le_sweep_deg is None):
            raise ValueError("give exactly one of le_sweep_mm / le_sweep_deg")
        if le_sweep_mm is None:
            le_sweep_mm = half_span_mm * math.tan(math.radians(le_sweep_deg))
        return cls(
            [Panel(root_chord_mm, tip_chord_mm, half_span_mm, le_sweep_mm)],
            ac_chord_fraction=ac_chord_fraction,
        )

    @classmethod
    def from_dict(cls, spec: dict) -> "Wing":
        """Build from a YAML mapping.

        Either a single trapezoid::

            root_chord_mm: 275
            tip_chord_mm: 107
            half_span_mm: 350
            le_sweep_mm: 217

        or a list of panels::

            panels:
              - {root_chord_mm: 275, tip_chord_mm: 180, span_mm: 120, le_sweep_mm: 60}
              - {root_chord_mm: 180, tip_chord_mm: 107, span_mm: 230, le_sweep_mm: 157}
        """
        ac = float(spec.get("ac_chord_fraction", 0.25))
        if "panels" in spec:
            panels = [
                Panel(
                    float(p["root_chord_mm"]),
                    float(p["tip_chord_mm"]),
                    float(p["span_mm"]),
                    float(p.get("le_sweep_mm", 0.0)),
                )
                for p in spec["panels"]
            ]
            return cls(panels, ac_chord_fraction=ac)
        return cls.trapezoidal(
            float(spec["root_chord_mm"]),
            float(spec["tip_chord_mm"]),
            float(spec["half_span_mm"]),
            le_sweep_mm=spec.get("le_sweep_mm"),
            le_sweep_deg=spec.get("le_sweep_deg"),
            ac_chord_fraction=ac,
        )

    # ---- planform ----------------------------------------------------------

    @property
    def placed_panels(self) -> list[Panel]:
        return list(self._placed)

    @property
    def half_span_mm(self) -> float:
        return sum(p.span_mm for p in self._placed)

    @property
    def span_mm(self) -> float:
        return 2.0 * self.half_span_mm

    @property
    def area_mm2(self) -> float:
        """Total (both sides) projected planform area."""
        return 2.0 * sum(p.area_mm2 for p in self._placed)

    @property
    def area_m2(self) -> float:
        return self.area_mm2 * 1e-6

    @property
    def area_dm2(self) -> float:
        return self.area_mm2 * 1e-4

    @property
    def aspect_ratio(self) -> float:
        return self.span_mm ** 2 / self.area_mm2

    @property
    def root_chord_mm(self) -> float:
        return self._placed[0].root_chord_mm

    @property
    def tip_chord_mm(self) -> float:
        return self._placed[-1].tip_chord_mm

    @property
    def taper_ratio(self) -> float:
        return self.tip_chord_mm / self.root_chord_mm

    # ---- MAC (exact area-weighted composition) -----------------------------

    def _weighted(self, attr: str) -> float:
        a = [p.area_mm2 for p in self._placed]
        v = [getattr(p, attr) for p in self._placed]
        return float(np.dot(a, v) / np.sum(a))

    @property
    def mac_mm(self) -> float:
        """Mean aerodynamic chord."""
        return self._weighted("mac_mm")

    @property
    def y_mac_mm(self) -> float:
        """Spanwise station of the MAC from the centreline ('d' in the calculator)."""
        return self._weighted("y_mac_mm")

    @property
    def x_le_mac_mm(self) -> float:
        """Leading edge of the MAC aft of the root LE ('C' in the calculator)."""
        return self._weighted("x_le_mac_mm")

    # ---- stability ---------------------------------------------------------

    @property
    def x_ac_mm(self) -> float:
        """Aerodynamic centre, aft of the root LE."""
        return self.x_le_mac_mm + self.ac_chord_fraction * self.mac_mm

    @property
    def x_np_mm(self) -> float:
        """Neutral point. For a tailless wing this is the wing AC."""
        return self.x_ac_mm

    def cg_for_static_margin(self, static_margin: float) -> float:
        """CG location (mm aft of root LE) giving the requested static margin.

        `static_margin` is a fraction of MAC (0.06 = 6 %).
        """
        return self.x_np_mm - static_margin * self.mac_mm

    def static_margin(self, x_cg_mm: float) -> float:
        """Static margin (fraction of MAC) for a given CG position."""
        return (self.x_np_mm - x_cg_mm) / self.mac_mm

    # ---- geometry helpers --------------------------------------------------

    def le_x_at(self, y_mm):
        """Leading-edge x at spanwise station(s) y (one side, 0..half span)."""
        return self._interp(np.asarray(y_mm, dtype=float), "le")

    def chord_at(self, y_mm):
        """Local chord at spanwise station(s) y."""
        return self._interp(np.asarray(y_mm, dtype=float), "chord")

    def _interp(self, y: np.ndarray, what: str):
        ys = [0.0] + [p.tip_y_mm for p in self._placed]
        if what == "le":
            vals = [0.0] + [p.tip_le_x_mm for p in self._placed]
        else:
            vals = [self.root_chord_mm] + [p.tip_chord_mm for p in self._placed]
        out = np.interp(np.abs(y), ys, vals)
        return float(out) if out.ndim == 0 else out

    def planform_centroid_x_mm(self, n: int = 2001) -> float:
        """Chordwise centroid of the planform area (useful for skin/core mass)."""
        y = np.linspace(0.0, self.half_span_mm, n)
        c = self.chord_at(y)
        xle = self.le_x_at(y)
        return float(_trapz(c * (xle + 0.5 * c), y) / _trapz(c, y))

    def outline(self) -> tuple[np.ndarray, np.ndarray]:
        """Closed planform outline (y, x) for plotting, both sides."""
        ys = np.array([0.0] + [p.tip_y_mm for p in self._placed])
        le = np.array([0.0] + [p.tip_le_x_mm for p in self._placed])
        ch = np.array([self.root_chord_mm] + [p.tip_chord_mm for p in self._placed])
        te = le + ch
        # right LE out, right TE back, left TE out, left LE back
        y = np.concatenate([ys, ys[::-1], -ys[1:], -ys[::-1]])
        x = np.concatenate([le, te[::-1], te[1:], le[::-1]])
        return y, x

    def summary(self) -> dict[str, float]:
        """The calculator's outputs, plus a few extras, as a flat dict."""
        return {
            "span_mm": self.span_mm,
            "area_mm2": self.area_mm2,
            "area_dm2": self.area_dm2,
            "aspect_ratio": self.aspect_ratio,
            "taper_ratio": self.taper_ratio,
            "mac_mm": self.mac_mm,
            "y_mac_mm": self.y_mac_mm,
            "x_le_mac_mm": self.x_le_mac_mm,
            "x_ac_mm": self.x_ac_mm,
            "le_sweep_deg_inboard": self._placed[0].le_sweep_deg,
            "c4_sweep_deg_inboard": self._placed[0].sweep_deg_at(0.25),
        }
