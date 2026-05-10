"""Generate the sizing/payload notebooks from source-of-truth Python strings.

Notebooks are checked in (so they render on GitHub), but this script lets us
regenerate them after editing cells without juggling JSON by hand.

Run from repo root:
    python scripts/build_notebooks.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _id(kind: str, source: str) -> str:
    """Deterministic 8-char cell id derived from kind + source.

    Stable across regeneration so reruns of this script only diff cells whose
    content actually changed.
    """
    h = hashlib.sha1(f"{kind}\0{source}".encode("utf-8")).hexdigest()
    return h[:8]


def md(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "id": _id("markdown", source),
        "metadata": {},
        "source": source.splitlines(keepends=True),
    }


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "id": _id("code", source),
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def notebook(cells: list[dict]) -> dict:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


# ---------- shared bootstrap snippet --------------------------------------- #

BOOTSTRAP = '''\
"""Add the repo root to sys.path so `import models` works from any subdir."""
import sys
from pathlib import Path

REPO_ROOT = Path.cwd()
while not (REPO_ROOT / "models").is_dir() and REPO_ROOT != REPO_ROOT.parent:
    REPO_ROOT = REPO_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

FIG_DIR = REPO_ROOT / "outputs" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

import yaml
import numpy as np
import matplotlib.pyplot as plt
'''


# ---------- 01: constraint analysis ---------------------------------------- #

NB01 = [
    md(
        "# 01 — Constraint Analysis\n\n"
        "Define the design point before any hardware is fixed. Outputs feed the\n"
        "mass and propulsion notebooks.\n\n"
        "**Inputs:** `mission/mission_params.yaml`, `airframe/airframe_params.yaml`\n\n"
        "**Outputs:** required T/W, disc loading vs endurance trade curve, minimum\n"
        "total thrust at target AUW.\n"
    ),
    code(BOOTSTRAP),
    code(
        '''\
with open(REPO_ROOT / "mission" / "mission_params.yaml") as f:
    mission = yaml.safe_load(f)
with open(REPO_ROOT / "airframe" / "airframe_params.yaml") as f:
    airframe = yaml.safe_load(f)

mission, airframe
'''
    ),
    md("## Required thrust at the design point\n"),
    code(
        '''\
from models import propulsion as prop

auw_kg = mission["design_point"]["target_auw_kg"]
tw = mission["design_point"]["thrust_to_weight_ratio"]
n_motors = airframe["airframe"]["num_motors"]
prop_d_in = airframe["airframe"]["max_prop_diameter_in"]
alt_m = mission["mission"]["altitude_asl_m"]

rho = prop.isa_density(alt_m, mission["environment"]["temperature_offset_c"])
T_per_motor_n = prop.thrust_per_motor(auw_kg, n_motors, tw)
T_total_n = T_per_motor_n * n_motors
A_disc = prop.disc_area_m2(prop_d_in, n_motors)
DL = prop.disc_loading(auw_kg * prop.G, A_disc)

print(f"Target AUW:                 {auw_kg:.2f} kg")
print(f"Air density @{alt_m} m:      {rho:.4f} kg/m^3")
print(f"Required T/W:               {tw:.2f}")
print(f"Total disc area:            {A_disc:.3f} m^2")
print(f"Hover disc loading:         {DL:.1f} N/m^2")
print(f"Required peak thrust/motor: {T_per_motor_n:.2f} N "
      f"({T_per_motor_n/prop.G*1000:.0f} gf)")
print(f"Required peak thrust total: {T_total_n:.2f} N")
'''
    ),
    md(
        "## Disc loading vs hover power\n\n"
        "Sweeps prop diameter to show the efficiency benefit of larger props at a\n"
        "fixed AUW. Lower disc loading → less induced power → longer endurance.\n"
    ),
    code(
        '''\
diameters_in = np.linspace(13, 22, 40)
A = prop.disc_area_m2(diameters_in, n_motors)
T_total = auw_kg * prop.G  # hover thrust
P_hover_w = np.array([
    prop.prop_power_estimate(T_total / n_motors, a / n_motors, rho) * n_motors
    for a in A
])
DL_arr = T_total / A

fig, ax1 = plt.subplots(figsize=(7, 4.5))
ax1.plot(diameters_in, P_hover_w, color="C0", label="Hover shaft power")
ax1.set_xlabel("Prop diameter [in]")
ax1.set_ylabel("Total hover shaft power [W]", color="C0")
ax1.tick_params(axis="y", labelcolor="C0")
ax1.axvline(prop_d_in, ls="--", color="grey", alpha=0.6,
            label=f"X6 max prop ({prop_d_in}\\")")

ax2 = ax1.twinx()
ax2.plot(diameters_in, DL_arr, color="C3", label="Disc loading")
ax2.set_ylabel("Hover disc loading [N/m^2]", color="C3")
ax2.tick_params(axis="y", labelcolor="C3")

ax1.set_title("Hover power vs prop diameter @ AUW = "
              f"{auw_kg} kg, {n_motors} motors, {alt_m} m ASL")
fig.tight_layout()
fig.savefig(FIG_DIR / "01_disc_loading_vs_power.png", dpi=140)
plt.show()
'''
    ),
    md(
        "## Optional: ADRpy constraint diagram\n\n"
        "If `ADRpy` is installed it can be used here to plot multirotor T/W vs\n"
        "disc loading constraints (climb, ceiling, gust margin). The block below\n"
        "is import-guarded so the notebook still runs end-to-end without it.\n"
    ),
    code(
        '''\
try:
    import ADRpy  # noqa: F401
    print("ADRpy available — extend this cell with constraint curves.")
except ModuleNotFoundError:
    print("ADRpy not installed; using simplified constraint plot above.")
'''
    ),
    md("## Outputs handed to notebook 02\n"),
    code(
        '''\
constraints_summary = {
    "auw_kg": auw_kg,
    "thrust_to_weight": tw,
    "thrust_total_n": T_total_n,
    "thrust_per_motor_n": T_per_motor_n,
    "disc_loading_n_m2": float(DL),
    "air_density_kg_m3": float(rho),
}
constraints_summary
'''
    ),
]


# ---------- 02: mass budget ------------------------------------------------ #

NB02 = [
    md(
        "# 02 — Mass Budget\n\n"
        "Bottom-up component rollup with a contingency factor and a tornado\n"
        "sensitivity chart. Parametric components (motors, ESCs, props, battery)\n"
        "are set in this notebook; hardware-fixed items come from\n"
        "`airframe_params.yaml`; payload contributions come from\n"
        "`payload_manifest.yaml`.\n"
    ),
    code(BOOTSTRAP),
    code(
        '''\
from models.mass_model import MassBudget

# Parametric components for the baseline X6 configuration.
# Edit these rows when the hardware shortlist changes.
parametric_g = {
    "motors_tarot_5008_340kv_x6":  6 * 158,   # ~158 g each incl. cable
    "esc_t-motor_alpha_60a_x6":    6 * 40,
    "props_18x55_cf_x6":            6 * 30,
    "battery_6s_16ah_li_ion":      1900,      # placeholder; swept in NB05
    "antivib_mount_+_skids":        180,
}

# Active payload bay configuration for this run.
active_payloads = ["global_shutter_rgb", "flir_boson_plus"]

mb = MassBudget.from_yaml(
    REPO_ROOT / "airframe" / "airframe_params.yaml",
    REPO_ROOT / "payload" / "payload_manifest.yaml",
    active_payloads=active_payloads,
    extra_components_g=parametric_g,
)

print(f"Dry mass:        {mb.dry_mass_g:>7.0f} g")
print(f"Contingency:     {mb.contingency_mass_g:>7.0f} g "
      f"({mb.contingency_fraction*100:.0f} %)")
print(f"Total AUW:       {mb.auw_g:>7.0f} g  ({mb.auw_kg:.3f} kg)")
'''
    ),
    md("## Component breakdown\n"),
    code(
        '''\
import pandas as pd

table = pd.DataFrame(mb.as_table(), columns=["component", "mass_g", "fraction_of_auw"])
table["fraction_of_auw"] = (table["fraction_of_auw"] * 100).round(1)
table
'''
    ),
    md(
        "## Tornado sensitivity\n\n"
        "Shows AUW reach if each component mass moves +/- 10 %. Long bars =\n"
        "candidates for tighter sourcing or aggressive weight reduction.\n"
    ),
    code(
        '''\
rows = mb.tornado(fraction=0.10)
names = [r[0] for r in rows]
lows = np.array([r[1] for r in rows])
highs = np.array([r[2] for r in rows])
baseline = mb.auw_kg

fig, ax = plt.subplots(figsize=(7, 0.35 * len(names) + 1.5))
y = np.arange(len(names))
ax.barh(y, highs - lows, left=lows, color="C0", alpha=0.8)
ax.axvline(baseline, color="k", ls="--", lw=1, label=f"baseline {baseline:.2f} kg")
ax.set_yticks(y)
ax.set_yticklabels(names)
ax.invert_yaxis()
ax.set_xlabel("AUW [kg]")
ax.set_title("Mass tornado — +/- 10 % per component")
ax.legend(loc="lower right")
fig.tight_layout()
fig.savefig(FIG_DIR / "02_mass_tornado.png", dpi=140)
plt.show()
'''
    ),
    md("## Hand-off to propulsion sizing\n"),
    code(
        '''\
mass_summary = {
    "auw_kg": mb.auw_kg,
    "dry_mass_g": mb.dry_mass_g,
    "contingency_fraction": mb.contingency_fraction,
    "active_payloads": active_payloads,
}
mass_summary
'''
    ),
]


# ---------- 03: propulsion sizing (stub-with-working-cells) --------------- #

NB03 = [
    md(
        "# 03 — Propulsion Sizing\n\n"
        "Pick a motor / prop / ESC combination that meets the T/W requirement\n"
        "from notebook 01 at the AUW from notebook 02.\n"
    ),
    code(BOOTSTRAP),
    code(
        '''\
with open(REPO_ROOT / "mission" / "mission_params.yaml") as f:
    mission = yaml.safe_load(f)
with open(REPO_ROOT / "airframe" / "airframe_params.yaml") as f:
    airframe = yaml.safe_load(f)

# Inputs (override here if running standalone)
auw_kg = mission["design_point"]["target_auw_kg"]
tw = mission["design_point"]["thrust_to_weight_ratio"]
hover_throttle = mission["design_point"]["hover_throttle_fraction"]
n_motors = airframe["airframe"]["num_motors"]
pack_voltage_nominal_v = 22.2  # 6S
pack_voltage_full_v = 25.2
prop_diameter_in = 18
'''
    ),
    md("## Required thrust per motor\n"),
    code(
        '''\
from models import propulsion as prop

T_peak_per_motor_n = prop.thrust_per_motor(
    auw_kg, n_motors, tw * mission["design_point"]["safety_factor"]
)
T_hover_per_motor_n = prop.hover_thrust_per_motor(auw_kg, n_motors)

print(f"Peak thrust per motor (with SF):  {T_peak_per_motor_n:.2f} N "
      f"({T_peak_per_motor_n/prop.G*1000:.0f} gf)")
print(f"Hover thrust per motor:           {T_hover_per_motor_n:.2f} N "
      f"({T_hover_per_motor_n/prop.G*1000:.0f} gf)")
print(f"Hover throttle target fraction:   {hover_throttle:.0%}")
'''
    ),
    md(
        "## KV target\n\n"
        "Rule of thumb: KV ≈ unloaded RPM target / pack voltage. Real loaded\n"
        "RPM sags 15–25 %.\n"
    ),
    code(
        '''\
# Target tip Mach ~0.5 for low noise; back-solve unloaded RPM target.
prop_d_m = prop_diameter_in * 0.0254
target_tip_speed_m_s = 170.0  # ~Mach 0.5 at sea level
rpm_target = (target_tip_speed_m_s * 60.0) / (np.pi * prop_d_m)
kv = prop.motor_kv_estimate(pack_voltage_full_v, rpm_target)

print(f"Target tip speed:        {target_tip_speed_m_s:.0f} m/s")
print(f"Unloaded RPM target:     {rpm_target:.0f} RPM")
print(f"Indicative motor KV:     {kv:.0f} rpm/V (at {pack_voltage_full_v} V full)")
'''
    ),
    md(
        "## Candidate motor/prop/ESC shortlist\n\n"
        "Fill in datasheet data (thrust, current, efficiency at the chosen prop)\n"
        "to compare. Below is a minimal placeholder table; replace values from\n"
        "manufacturer test reports.\n"
    ),
    code(
        '''\
import pandas as pd

candidates = pd.DataFrame([
    {"motor": "Tarot 5008 340 KV", "prop": "1855 CF",
     "hover_thrust_g": 1100, "hover_current_a": 8.0, "peak_current_a": 28.0,
     "efficiency_g_per_w": 8.5},
    {"motor": "T-MOTOR MN505-S 320 KV", "prop": "1855 CF",
     "hover_thrust_g": 1180, "hover_current_a": 7.5, "peak_current_a": 32.0,
     "efficiency_g_per_w": 9.2},
    {"motor": "Sunnysky X4108S 380 KV", "prop": "1755 CF",
     "hover_thrust_g": 980,  "hover_current_a": 8.8, "peak_current_a": 26.0,
     "efficiency_g_per_w": 7.8},
])

T_hover_per_motor_g = T_hover_per_motor_n / prop.G * 1000
candidates["hover_margin_g"] = candidates["hover_thrust_g"] - T_hover_per_motor_g
candidates["esc_min_a_20pct_headroom"] = (candidates["peak_current_a"] * 1.20).round(1)
candidates
'''
    ),
    md("## Hover power estimate (momentum theory)\n"),
    code(
        '''\
rho = prop.isa_density(mission["mission"]["altitude_asl_m"])
A_disc_per_motor = prop.disc_area_m2(prop_diameter_in, 1)
P_hover_per_motor_w = prop.prop_power_estimate(T_hover_per_motor_n, A_disc_per_motor, rho)
P_hover_total_w = P_hover_per_motor_w * n_motors
I_hover_pack_a = P_hover_total_w / pack_voltage_nominal_v

print(f"Hover shaft power per motor: {P_hover_per_motor_w:.0f} W")
print(f"Hover shaft power total:     {P_hover_total_w:.0f} W")
print(f"Implied pack current @ {pack_voltage_nominal_v} V: {I_hover_pack_a:.1f} A")
print("(Multiply by ~1/eta_motor_esc ~ 0.85 for electrical pack current.)")
'''
    ),
    md("## Hand-off to power + endurance notebooks\n"),
    code(
        '''\
propulsion_summary = {
    "n_motors": n_motors,
    "prop_diameter_in": prop_diameter_in,
    "kv_indicative": float(kv),
    "hover_thrust_per_motor_n": T_hover_per_motor_n,
    "peak_thrust_per_motor_n": T_peak_per_motor_n,
    "hover_shaft_power_total_w": P_hover_total_w,
    "hover_pack_current_a": I_hover_pack_a,
    "pack_voltage_nominal_v": pack_voltage_nominal_v,
}
propulsion_summary
'''
    ),
]


# ---------- 04: power budget --------------------------------------------- #

NB04 = [
    md(
        "# 04 — Power Budget\n\n"
        "Multi-rail power architecture for avionics + payload. Propulsion is\n"
        "tracked separately via notebook 03.\n"
    ),
    code(BOOTSTRAP),
    code(
        '''\
from models.power_model import PowerBudget

pb = PowerBudget()
pb.add_rail("main_6s",   voltage_v=22.2, capacity_a=None)  # propulsion pack
pb.add_rail("reg_5v",    voltage_v=5.0,  capacity_a=8.0)
pb.add_rail("reg_12v",   voltage_v=12.0, capacity_a=5.0)
pb.add_rail("sensor_5v", voltage_v=5.0,  capacity_a=4.0)
'''
    ),
    md("## Avionics + payload consumers\n"),
    code(
        '''\
# Edit datasheet values here as hardware is selected.
pb.add_consumer("pixhawk_6x",        "reg_5v",    idle_a=0.20, peak_a=0.40)
pb.add_consumer("rc_rx_elrs",        "reg_5v",    idle_a=0.05, peak_a=0.10)
pb.add_consumer("rtk_h_rtk_f9p",     "reg_5v",    idle_a=0.15, peak_a=0.20)
pb.add_consumer("orin_nano_carrier", "reg_12v",   idle_a=0.50, peak_a=1.50, duty_cycle=0.7)
pb.add_consumer("livox_mid360",      "reg_12v",   idle_a=0.30, peak_a=0.75, duty_cycle=1.0)
pb.add_consumer("flir_boson_plus",   "sensor_5v", idle_a=0.30, peak_a=0.50)
pb.add_consumer("global_shutter_rgb","sensor_5v", idle_a=0.40, peak_a=0.80)

import pandas as pd
totals = pd.DataFrame(pb.rail_totals()).T
totals.round(3)
'''
    ),
    md("## BEC / UBEC sizing recommendation\n"),
    code(
        '''\
recs = pb.bec_recommendation(headroom=0.20)
for rail, a in recs.items():
    print(f"{rail:<10s} -> {a:.2f} A continuous (peak * 1.20)")

warnings = pb.warnings()
if warnings:
    print("\\nWARNINGS:")
    for w in warnings:
        print(" -", w)
else:
    print("\\nNo rail capacity violations.")
'''
    ),
    md("## Hand-off: total avionics+payload power\n"),
    code(
        '''\
power_summary = {
    "avionics_payload_average_w": pb.total_average_w(),
    "rail_totals": pb.rail_totals(),
}
power_summary
'''
    ),
]


# ---------- 05: endurance ------------------------------------------------- #

NB05 = [
    md(
        "# 05 — Endurance Estimate\n\n"
        "Battery capacity → hover endurance with Peukert correction. Sweeps\n"
        "capacity and payload configuration; marks the 20 % reserve threshold.\n"
    ),
    code(BOOTSTRAP),
    code(
        '''\
from models import endurance as ed

# Replace this with the value from notebook 03 in a multi-notebook run.
hover_pack_current_a = 30.0  # A, indicative for 6S X6 @ 6.5 kg
pack_voltage_nominal_v = 22.2

capacities_ah = np.linspace(10, 22, 25)
peukert_n = 1.10  # LiPo; use 1.05 for high-quality Li-ion

# Three illustrative payload deltas in additional pack current at hover.
configs = {
    "light  (rgb only)":   0.0,
    "medium (rgb+thermal)": 1.0,
    "heavy  (lidar+altum)": 3.0,
}

fig, ax = plt.subplots(figsize=(7, 4.5))
for label, dI in configs.items():
    minutes = ed.sweep_capacity(
        capacities_ah,
        hover_current_a=hover_pack_current_a + dI,
        nominal_voltage_v=pack_voltage_nominal_v,
        peukert_exponent=peukert_n,
        usable_fraction=0.80,
    )
    ax.plot(capacities_ah, minutes, label=label)

ax.axhline(20, color="grey", ls="--", lw=1, label="20 min target")
ax.set_xlabel("Battery capacity [Ah, 6S]")
ax.set_ylabel("Hover endurance [min, 20 % reserve]")
ax.set_title("Endurance vs capacity, Peukert n = " f"{peukert_n}")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(FIG_DIR / "05_endurance_curves.png", dpi=140)
plt.show()
'''
    ),
    md(
        "## Endurance surface (capacity x payload)\n\n"
        "Useful when reviewing pack options against a payload menu. Replace the\n"
        "axes with measured per-config hover currents from notebook 04 once\n"
        "those numbers settle.\n"
    ),
    code(
        '''\
delta_i_a = np.linspace(0, 5, 25)
CC, DD = np.meshgrid(capacities_ah, delta_i_a)
ZZ = np.empty_like(CC)
for i in range(CC.shape[0]):
    ZZ[i, :] = ed.sweep_capacity(
        CC[i, :],
        hover_current_a=hover_pack_current_a + DD[i, 0],
        peukert_exponent=peukert_n,
    )

fig, ax = plt.subplots(figsize=(7, 5))
cs = ax.contourf(CC, DD, ZZ, levels=15, cmap="viridis")
ax.contour(CC, DD, ZZ, levels=[20], colors="white", linewidths=2)
ax.set_xlabel("Battery capacity [Ah]")
ax.set_ylabel("Payload current adder [A]")
ax.set_title("Hover endurance [min]")
fig.colorbar(cs, ax=ax)
fig.tight_layout()
fig.savefig(FIG_DIR / "05_endurance_surface.png", dpi=140)
plt.show()
'''
    ),
]


# ---------- 06: payload trades ------------------------------------------- #

NB06 = [
    md(
        "# 06 — Payload Trade Study\n\n"
        "Enumerate valid swap-bay payload configurations, filter by mass and\n"
        "power budget limits, and rank by endurance impact.\n"
    ),
    code(BOOTSTRAP),
    code(
        '''\
from itertools import combinations

with open(REPO_ROOT / "payload" / "payload_manifest.yaml") as f:
    manifest = yaml.safe_load(f)

payloads = manifest["payloads"]
limits = manifest["limits"]
always_on = {n: s for n, s in payloads.items() if s.get("always_on")}
swappable = {n: s for n, s in payloads.items() if not s.get("always_on")}

print("Always-on:", list(always_on))
print("Swappable:", list(swappable))
print("Limits:   ", limits)
'''
    ),
    md("## Enumerate valid configurations\n"),
    code(
        '''\
import pandas as pd

base_mass_g  = sum(s["mass_g"]  for s in always_on.values())
base_power_w = sum(s["power_w"] for s in always_on.values())

rows = []
max_n = limits["max_simultaneous_swap_bays"]
for k in range(0, max_n + 1):
    for combo in combinations(swappable.keys(), k):
        mass_g  = base_mass_g  + sum(swappable[n]["mass_g"]  for n in combo)
        power_w = base_power_w + sum(swappable[n]["power_w"] for n in combo)
        valid = (mass_g <= limits["max_payload_mass_g"]
                 and power_w <= limits["max_payload_power_w"])
        rows.append({
            "swap_bays": ", ".join(combo) if combo else "(none)",
            "n_bays": k,
            "total_mass_g": mass_g,
            "total_power_w": power_w,
            "valid": valid,
        })

configs = pd.DataFrame(rows).sort_values(["valid", "total_mass_g"],
                                         ascending=[False, True])
configs.reset_index(drop=True, inplace=True)
configs
'''
    ),
    md(
        "## Endurance impact per configuration\n\n"
        "Rough first-cut: assume hover current scales linearly with payload\n"
        "weight via a configuration-independent disc-loading model. Refine by\n"
        "feeding each config back through notebooks 03/05 once shortlisted.\n"
    ),
    code(
        '''\
from models import propulsion as prop, endurance as ed

# Baseline (light) operating point — replace with NB03/NB05 values.
baseline_auw_kg = 6.5
baseline_hover_current_a = 30.0
pack_voltage_v = 22.2
prop_diameter_in = 18
n_motors = 6
rho = prop.isa_density(500)
A_per_motor = prop.disc_area_m2(prop_diameter_in, 1)

def estimate_hover_current(extra_payload_g: float) -> float:
    auw_kg = baseline_auw_kg + extra_payload_g / 1000.0
    T_per = prop.hover_thrust_per_motor(auw_kg, n_motors)
    P_total = prop.prop_power_estimate(T_per, A_per_motor, rho) * n_motors
    return P_total / pack_voltage_v / 0.85  # ~85 % motor+ESC efficiency

baseline_payload_g = base_mass_g  # always-on only
configs["hover_current_a"] = configs["total_mass_g"].apply(
    lambda m: estimate_hover_current(m - baseline_payload_g) + baseline_hover_current_a
              - estimate_hover_current(0)
)

configs["endurance_min_16ah"] = configs["hover_current_a"].apply(
    lambda i: ed.hover_endurance_min(ed.Battery(capacity_ah=16.0), i)
)
configs.loc[configs["valid"]].sort_values("endurance_min_16ah", ascending=False)
'''
    ),
]


# ---------- write everything --------------------------------------------- #

OUTPUTS = {
    ROOT / "sizing"  / "01_constraint_analysis.ipynb": NB01,
    ROOT / "sizing"  / "02_mass_budget.ipynb":          NB02,
    ROOT / "sizing"  / "03_propulsion_sizing.ipynb":    NB03,
    ROOT / "sizing"  / "04_power_budget.ipynb":         NB04,
    ROOT / "sizing"  / "05_endurance_estimate.ipynb":   NB05,
    ROOT / "payload" / "06_payload_trades.ipynb":       NB06,
}


def main() -> None:
    for path, cells in OUTPUTS.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(notebook(cells), indent=1))
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
