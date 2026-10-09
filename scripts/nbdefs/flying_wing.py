"""Flying-wing sizing notebooks — source of truth.

Flow:
    01 constraint analysis   W/S vs P/m matching chart, stall + launch limits
    02 geometry and CG       MAC, neutral point, target CG for the static margin
    03 mass and balance      component rollup, battery placement, CG check
    04 aero performance      drag polar, power-required curve, stall-limited speeds
    05 propulsion/endurance  cruise power -> shared Peukert endurance, capacity sweep
"""

from ._nb import bootstrap, code, md

LOAD = '''\
with open(REPO_ROOT / "mission" / "mission_params.yaml") as f:
    mission = yaml.safe_load(f)
with open(PLATFORM_DIR / "design_point.yaml") as f:
    design = yaml.safe_load(f)
with open(PLATFORM_DIR / "airframe_params.yaml") as f:
    airframe = yaml.safe_load(f)

from uavdesign.atmosphere import G, isa_density, wing_loading_g_dm2, wing_loading_n_m2
from uavdesign.aero import Wing, DragPolar, FixedWingAero

alt_m = mission["mission"]["altitude_asl_m"]
rho = isa_density(alt_m, mission["environment"]["temperature_offset_c"])
wing = Wing.from_dict(airframe["wing"])
aero = design["aero"]
perf = design["performance"]
mass_kg = design["design_point"]["target_auw_kg"]
static_margin = design["design_point"]["static_margin"]
polar = DragPolar.from_oswald(aero["cd0"], wing.aspect_ratio, aero["oswald_e"], aero["cl_max"])

print(f"Site: {alt_m} m ASL, rho = {rho:.4f} kg/m^3")
print(f"Wing: S = {wing.area_dm2:.2f} dm^2, b = {wing.span_mm:.0f} mm, AR = {wing.aspect_ratio:.2f}")
print(f"Polar: CD0 = {polar.cd0}, k = {polar.k:.4f}, CLmax = {polar.cl_max}")
'''


# ---------- 01: constraint analysis --------------------------------------- #

NB01 = [
    md(
        "# 01 — Constraint Analysis (flying wing)\n\n"
        "Matching chart: required shaft power per kilogram vs wing loading. Each\n"
        "performance requirement becomes a curve; stall and hand-launch become\n"
        "vertical limits. The feasible design space is above every curve and left\n"
        "of every limit.\n\n"
        "**Inputs:** `mission/mission_params.yaml`, `design_point.yaml`,\n"
        "`airframe_params.yaml` (aspect ratio sets the induced-drag factor).\n\n"
        "**Outputs:** maximum allowable W/S, required shaft power at the design point.\n"
    ),
    code(bootstrap("flying_wing")),
    code(LOAD),
    md("## Constraint curves\n"),
    code(
        '''\
from uavdesign.aero import constraint as con

eta_p = design["propulsion"]["prop_efficiency"]
ws = np.linspace(20, 160, 400)  # N/m^2

v_cr, v_cl, v_tn = perf["cruise_speed_m_s"], perf["climb_speed_m_s"], perf["turn_speed_m_s"]
curves = {
    f"cruise @ {v_cr:.0f} m/s": con.power_per_mass_w_kg(
        con.cruise_tw(ws, rho, v_cr, polar.cd0, polar.k), v_cr, eta_p),
    f"climb {perf['climb_rate_m_s']:.0f} m/s @ {v_cl:.0f} m/s": con.power_per_mass_w_kg(
        con.climb_tw(ws, rho, v_cl, polar.cd0, polar.k, perf["climb_rate_m_s"]), v_cl, eta_p),
    f"{perf['turn_bank_deg']:.0f} deg sustained turn @ {v_tn:.0f} m/s": con.power_per_mass_w_kg(
        con.turn_tw(ws, rho, v_tn, polar.cd0, polar.k, perf["turn_bank_deg"]), v_tn, eta_p),
}
envelope = np.max(np.vstack(list(curves.values())), axis=0)

def ws_limits(cl_max):
    return (
        con.stall_ws_max(rho, perf["max_stall_speed_m_s"], cl_max),
        con.launch_ws_max(rho, perf["launch_speed_m_s"], cl_max, perf["launch_margin"]),
    )

ws_stall, ws_launch = ws_limits(polar.cl_max)
ws_limit = min(ws_stall, ws_launch)
ws_design = mass_kg * G / wing.area_m2
p_design = float(np.interp(ws_design, ws, envelope))

print(f"Stall limit  (Vs <= {perf['max_stall_speed_m_s']} m/s):   W/S <= {ws_stall:6.1f} N/m^2 "
      f"({wing_loading_g_dm2(ws_stall):.1f} g/dm^2)")
print(f"Launch limit ({perf['launch_speed_m_s']} m/s, {perf['launch_margin']} Vs): W/S <= {ws_launch:6.1f} N/m^2 "
      f"({wing_loading_g_dm2(ws_launch):.1f} g/dm^2)")
print(f"Design point: W/S = {ws_design:.1f} N/m^2 ({wing_loading_g_dm2(ws_design):.1f} g/dm^2), "
      f"needs {p_design:.0f} W/kg shaft")
print("Design point is", "FEASIBLE" if ws_design <= ws_limit else "OUTSIDE the stall/launch limit")
'''
    ),
    md(
        "## Matching chart\n\n"
        "Dotted verticals show how the binding W/S limit moves with CLmax — the\n"
        "single most uncertain input for a reflexed flying-wing section.\n"
    ),
    code(
        '''\
fig, ax = plt.subplots(figsize=(8, 5))
for label, y in curves.items():
    ax.plot(ws, y, label=label)

top = float(np.nanmax(envelope[ws <= 160])) * 1.15
feasible = ws <= ws_limit
ax.fill_between(ws[feasible], envelope[feasible], top, color="C2", alpha=0.12, label="feasible")
ax.axvline(ws_stall, color="k", lw=1.5, label=f"stall limit (CLmax {polar.cl_max})")
ax.axvline(ws_launch, color="k", lw=1.5, ls="--", label="hand-launch limit")
for cl in aero["cl_max_sweep"]:
    if cl == polar.cl_max:
        continue
    lim = min(ws_limits(cl))
    ax.axvline(lim, color="grey", lw=0.8, ls=":")
    ax.text(lim, top * 0.97, f"{cl}", rotation=90, va="top", ha="right", fontsize=8, color="grey")
ax.plot(ws_design, p_design, "o", color="C3", ms=9, label="baseline design")

ax.set_xlim(ws[0], ws[-1])
ax.set_ylim(0, top)
ax.set_xlabel("Wing loading W/S [N/m^2]")
ax.set_ylabel("Required shaft power [W/kg]")
sec = ax.secondary_xaxis("top", functions=(wing_loading_g_dm2, wing_loading_n_m2))
sec.set_xlabel("Wing loading [g/dm^2]")
ax.set_title(f"Flying-wing matching chart, {alt_m} m ASL, eta_prop = {eta_p}")
ax.legend(loc="lower right", fontsize=8)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(FIG_DIR / "01_matching_chart.png", dpi=140)
plt.show()
'''
    ),
    md("## Outputs handed to notebook 02\n"),
    code(
        '''\
constraints_summary = {
    "ws_limit_n_m2": float(ws_limit),
    "ws_limit_g_dm2": float(wing_loading_g_dm2(ws_limit)),
    "ws_design_n_m2": float(ws_design),
    "required_shaft_w_per_kg": p_design,
    "required_shaft_w": p_design * mass_kg,
    "min_wing_area_dm2_at_target_mass": mass_kg * G / ws_limit * 100,
}
constraints_summary
'''
    ),
]


# ---------- 02: geometry and CG ------------------------------------------- #

NB02 = [
    md(
        "# 02 — Wing Geometry and Target CG\n\n"
        "Mean aerodynamic chord, neutral point and the CG location that gives the\n"
        "chosen static margin. The first cell cross-checks the model against the\n"
        "rcplanes.online flying-wing CG calculator for the baseline planform\n"
        "(the same numbers are locked in by `tests/test_wing.py`).\n\n"
        "**Datum:** x = 0 at the wing root leading edge, positive aft (mm).\n"
    ),
    code(bootstrap("flying_wing")),
    code(LOAD),
    md("## Planform summary vs calculator\n"),
    code(
        '''\
import pandas as pd

calculator = {   # rcplanes.online, root 275 / tip 107 / half span 350 / sweep 217 / SM 6 %
    "mac_mm": 203.31, "x_le_mac_mm": 92.59, "y_mac_mm": 149.35,
    "x_ac_mm": 143.42, "area_dm2": 13.37, "aspect_ratio": 3.66,
}
summary = wing.summary()
x_cg_target = wing.cg_for_static_margin(static_margin)
summary[f"x_cg_mm @ SM {static_margin:.0%}"] = x_cg_target
calculator[f"x_cg_mm @ SM {static_margin:.0%}"] = 131.22

pd.DataFrame({
    "model": pd.Series(summary).round(2),
    "calculator": pd.Series(calculator),
})
'''
    ),
    md(
        "## Planform with MAC, neutral point and target CG\n\n"
        "Leading edge at the top, as in the calculator. The shaded band on the\n"
        "centreline is the usable battery bay.\n"
    ),
    code(
        '''\
y, x = wing.outline()
bay = airframe["battery_bay_x_mm"]

fig, ax = plt.subplots(figsize=(8, 4.5))
ax.fill(y, x, color="C0", alpha=0.15)
ax.plot(y, x, color="C0", lw=1.5)
for side in (-1, 1):
    ax.plot([side * wing.y_mac_mm] * 2,
            [wing.x_le_mac_mm, wing.x_le_mac_mm + wing.mac_mm], color="C3", lw=2)
ax.text(wing.y_mac_mm + 6, wing.x_le_mac_mm + wing.mac_mm / 2, "MAC", color="C3", fontsize=9)
ax.axhspan(bay[0], bay[1], xmin=0.47, xmax=0.53, color="C1", alpha=0.35)
ax.axhline(wing.x_np_mm, color="C0", ls="--", lw=1, label=f"neutral point {wing.x_np_mm:.1f} mm")
ax.axhline(x_cg_target, color="k", lw=1.2,
           label=f"target CG {x_cg_target:.1f} mm (SM {static_margin:.0%})")
ax.plot(0, x_cg_target, marker="o", color="k")
ax.set_aspect("equal")
ax.invert_yaxis()
ax.set_xlabel("y, spanwise [mm]")
ax.set_ylabel("x, aft of root LE [mm]")
ax.set_title(f"Planform: S = {wing.area_dm2:.2f} dm^2, AR = {wing.aspect_ratio:.2f}, "
             f"LE sweep {wing.placed_panels[0].le_sweep_deg:.1f} deg")
ax.legend(loc="lower center", fontsize=8)
fig.tight_layout()
fig.savefig(FIG_DIR / "02_planform_cg.png", dpi=140)
plt.show()
'''
    ),
    md(
        "## CG position vs static margin\n\n"
        "1 % (expert, light elevator) to 10 % (beginner, stable). Every 1 % of\n"
        "margin moves the CG forward by 1 % of MAC.\n"
    ),
    code(
        '''\
sms = np.linspace(0.0, 0.12, 25)
fig, ax = plt.subplots(figsize=(7, 3.5))
ax.plot(sms * 100, [wing.cg_for_static_margin(s) for s in sms])
ax.axvspan(1, 10, color="C2", alpha=0.08, label="usual range 1-10 %")
ax.axvline(static_margin * 100, color="k", ls="--", lw=1)
ax.set_xlabel("Static margin [% MAC]")
ax.set_ylabel("CG aft of root LE [mm]")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(FIG_DIR / "02_cg_vs_static_margin.png", dpi=140)
plt.show()
'''
    ),
    md(
        "## Scaling the planform to a wing loading\n\n"
        "If notebook 01 says the wing is too heavily loaded, a geometric scale of\n"
        "the whole planform (same shape, same sweep angle) by `sqrt(S_req / S)`\n"
        "keeps every ratio above and moves the CG proportionally.\n"
    ),
    code(
        '''\
from uavdesign.aero import constraint as con

ws_limit = min(
    con.stall_ws_max(rho, perf["max_stall_speed_m_s"], polar.cl_max),
    con.launch_ws_max(rho, perf["launch_speed_m_s"], polar.cl_max, perf["launch_margin"]),
)
s_req_m2 = mass_kg * G / ws_limit
scale = np.sqrt(max(s_req_m2 / wing.area_m2, 1.0))
print(f"Area needed at {mass_kg:.2f} kg: {s_req_m2*100:.2f} dm^2 (have {wing.area_dm2:.2f})")
print(f"Linear scale factor: {scale:.3f}" + ("  (no change needed)" if scale == 1.0 else ""))
'''
    ),
    md("## Outputs handed to notebook 03\n"),
    code(
        '''\
geometry_summary = {
    "mac_mm": wing.mac_mm,
    "x_np_mm": wing.x_np_mm,
    "static_margin": static_margin,
    "x_cg_target_mm": x_cg_target,
}
geometry_summary
'''
    ),
]


# ---------- 03: mass and balance ------------------------------------------ #

NB03 = [
    md(
        "# 03 — Mass and Balance\n\n"
        "Shared `MassBudget` with component positions. Everything except the\n"
        "battery is fixed by the airframe YAML; the battery is slid fore/aft to put\n"
        "the CG on the target from notebook 02, then checked against the pod.\n\n"
        "Payloads come from the **shared** `payload/payload_manifest.yaml`; the\n"
        "multirotor's always-on compute stack is excluded on this airframe.\n"
    ),
    code(bootstrap("flying_wing")),
    code(LOAD),
    code(
        '''\
from uavdesign.mass import MassBudget

payloads = design["payloads"]
batt = design["battery"]
bay = airframe["battery_bay_x_mm"]

mb = MassBudget.from_yaml(
    PLATFORM_DIR / "airframe_params.yaml",
    REPO_ROOT / "payload" / "payload_manifest.yaml",
    active_payloads=payloads,
    include_always_on=False,
    payload_positions_mm={n: design["payload_x_mm"] for n in payloads},
)
mb.add("battery", batt["mass_g"])

x_cg_target = wing.cg_for_static_margin(static_margin)
x_batt_ideal = mb.solve_position_for_cg("battery", x_cg_target)
x_batt = float(np.clip(x_batt_ideal, *bay))
mb.set_position("battery", x_batt)
sm_actual = wing.static_margin(mb.cg_x_mm())

print(f"Target CG:            {x_cg_target:6.1f} mm (SM {static_margin:.1%})")
print(f"Battery position:     {x_batt_ideal:6.1f} mm ideal, bay {bay[0]}-{bay[1]} mm")
print(f"Resulting CG:         {mb.cg_x_mm():6.1f} mm (SM {sm_actual:.1%})")
print(f"AUW:                  {mb.auw_g:6.0f} g  (target {mass_kg*1000:.0f} g, "
      f"margin {mass_kg*1000 - mb.auw_g:+.0f} g)")
'''
    ),
    md(
        "## Ballast check\n\n"
        "If the battery cannot reach the ideal position, this is the nose (or\n"
        "tail) ballast needed at the bay end to restore the target margin.\n"
    ),
    code(
        '''\
x_now, m_now = mb.cg_x_mm(), mb.dry_mass_g
if np.isclose(x_batt, x_batt_ideal):
    print("Battery reaches the ideal position — no ballast needed.")
else:
    x_ballast = bay[0] if x_batt_ideal < bay[0] else bay[1]
    ballast_g = m_now * (x_now - x_cg_target) / (x_cg_target - x_ballast)
    print(f"Ballast needed: {ballast_g:.0f} g at x = {x_ballast} mm")
'''
    ),
    md("## Component table\n"),
    code(
        '''\
import pandas as pd

rows = [
    {"component": n, "mass_g": m, "x_mm": mb.positions_mm[n],
     "moment_g_mm": m * mb.positions_mm[n]}
    for n, m in mb.components_g.items()
]
table = pd.DataFrame(rows).sort_values("mass_g", ascending=False)
table["fraction_of_auw_pct"] = (table["mass_g"] / mb.auw_g * 100).round(1)
table.round(1)
'''
    ),
    md(
        "## Static margin vs battery position\n\n"
        "The slope shows how sensitive trim is to where the pack sits — on a\n"
        "sub-kilogram wing a few millimetres matter.\n"
    ),
    code(
        '''\
xs = np.linspace(bay[0] - 30, bay[1] + 30, 200)
sm_curve = []
for xb in xs:
    mb.set_position("battery", xb)
    sm_curve.append(wing.static_margin(mb.cg_x_mm()))
mb.set_position("battery", x_batt)

fig, ax = plt.subplots(figsize=(7, 4))
ax.plot(xs, np.array(sm_curve) * 100)
ax.axvspan(*bay, color="C1", alpha=0.15, label="battery bay")
ax.axhline(static_margin * 100, color="k", ls="--", lw=1, label="target SM")
ax.axhline(0, color="C3", lw=1, label="neutral (unstable aft)")
ax.plot(x_batt, sm_actual * 100, "o", color="k")
ax.set_xlabel("Battery CG position [mm aft of root LE]")
ax.set_ylabel("Static margin [% MAC]")
ax.legend(fontsize=8)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(FIG_DIR / "03_sm_vs_battery_position.png", dpi=140)
plt.show()
'''
    ),
    md("## Mass tornado (shared model)\n"),
    code(
        '''\
rows = mb.tornado(fraction=0.10)
names = [r[0] for r in rows]
lows = np.array([r[1] for r in rows]) * 1000
highs = np.array([r[2] for r in rows]) * 1000

fig, ax = plt.subplots(figsize=(7, 0.35 * len(names) + 1.5))
yy = np.arange(len(names))
ax.barh(yy, highs - lows, left=lows, color="C0", alpha=0.8)
ax.axvline(mb.auw_g, color="k", ls="--", lw=1, label=f"baseline {mb.auw_g:.0f} g")
ax.set_yticks(yy)
ax.set_yticklabels(names)
ax.invert_yaxis()
ax.set_xlabel("AUW [g]")
ax.set_title("Mass tornado — +/- 10 % per component")
ax.legend(loc="lower right")
fig.tight_layout()
fig.savefig(FIG_DIR / "03_mass_tornado.png", dpi=140)
plt.show()
'''
    ),
    md("## Outputs handed to notebooks 04/05\n"),
    code(
        '''\
balance_summary = {
    "auw_kg": mb.auw_kg,
    "battery_x_mm": x_batt,
    "cg_x_mm": mb.cg_x_mm(),
    "static_margin": sm_actual,
    "mass_without_battery_g": mb.dry_mass_g - batt["mass_g"],
    "contingency_fraction": mb.contingency_fraction,
}
balance_summary
'''
    ),
]


# ---------- 04: aero performance ------------------------------------------ #

NB04 = [
    md(
        "# 04 — Aerodynamic Performance\n\n"
        "Parabolic drag polar at the design mass: characteristic speeds,\n"
        "power-required curve and L/D. Every optimum speed is checked against\n"
        "stall — on a low-AR flying wing with a reflexed section the theoretical\n"
        "best-endurance speed is often below stall, so the aircraft is\n"
        "stall-limited rather than drag-limited.\n\n"
        "Uses the design target mass; swap in `balance_summary['auw_kg']` from\n"
        "notebook 03 once the mass budget is real.\n"
    ),
    code(bootstrap("flying_wing")),
    code(LOAD),
    code(
        '''\
from uavdesign import propulsion as prop

ac = FixedWingAero(mass_kg, wing.area_m2, polar, rho)
pp = design["propulsion"]
vs = ac.stall_speed()
limited = ac.stall_limited(margin=1.2)
v_endurance = max(ac.v_min_power, 1.2 * vs)
v_range = max(ac.v_max_ld, 1.2 * vs)

def flag(name):
    return "  <-- below 1.2 Vs, stall-limited" if limited[name] else ""

print(f"Wing loading:            {ac.wing_loading_n_m2:.1f} N/m^2 "
      f"({wing_loading_g_dm2(ac.wing_loading_n_m2):.1f} g/dm^2)")
print(f"Stall speed (CLmax {polar.cl_max}): {vs:5.1f} m/s ({vs*3.6:.0f} km/h)")
print(f"Min-power speed:         {ac.v_min_power:5.1f} m/s  (CL {polar.cl_min_power:.2f}){flag('v_min_power')}")
print(f"Best-L/D speed:          {ac.v_max_ld:5.1f} m/s  (CL {polar.cl_max_ld:.2f}){flag('v_max_ld')}")
print(f"L/D max (unconstrained): {polar.ld_max:5.1f}")
print(f"-> best endurance speed: {v_endurance:5.1f} m/s, best range speed: {v_range:5.1f} m/s")
print(f"Cruise ({perf['cruise_speed_m_s']} m/s):          CL {float(ac.cl(perf['cruise_speed_m_s'])):.2f}, "
      f"L/D {float(ac.lift_to_drag(perf['cruise_speed_m_s'])):.1f}")
'''
    ),
    md("## Power required and L/D vs airspeed\n"),
    code(
        '''\
v = np.linspace(0.8 * vs, 30, 300)
p_aero = ac.aero_power_w(v)
p_shaft = p_aero / pp["prop_efficiency"]
p_elec = prop.electrical_power_w(p_shaft, pp["motor_efficiency"], pp["esc_efficiency"]) \\
    + pp["avionics_power_w"]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
ax1.plot(v, p_aero, label="aero  D*V")
ax1.plot(v, p_shaft, label="shaft  / eta_prop")
ax1.plot(v, p_elec, label="electrical  / eta_motor*eta_esc + avionics")
for a in (ax1, ax2):
    a.axvspan(v[0], vs, color="C3", alpha=0.12)
    a.axvline(1.2 * vs, color="C3", ls=":", lw=1)
    a.axvline(perf["cruise_speed_m_s"], color="k", ls="--", lw=1)
    a.set_xlabel("Airspeed [m/s]")
    a.grid(alpha=0.3)
ax1.set_ylabel("Power [W]")
ax1.set_ylim(0, float(p_elec.max()))
ax1.legend(fontsize=8)
ax1.set_title("Power required (shaded: below stall; dotted: 1.2 Vs)")
ax2.plot(v, ac.lift_to_drag(v), color="C2")
ax2.set_ylabel("L/D")
ax2.set_title("Lift-to-drag ratio")
fig.tight_layout()
fig.savefig(FIG_DIR / "04_power_required.png", dpi=140)
plt.show()
'''
    ),
    md(
        "## Sensitivity to CLmax\n\n"
        "The online calculator assumes CLmax = 1.0 at sea level. A trimmed,\n"
        "reflexed flying-wing section is closer to 0.6-0.8.\n"
    ),
    code(
        '''\
import pandas as pd
from uavdesign.atmosphere import RHO0

rows = []
for cl in aero["cl_max_sweep"]:
    p = DragPolar(polar.cd0, polar.k, cl)
    here = FixedWingAero(mass_kg, wing.area_m2, p, rho)
    sea = FixedWingAero(mass_kg, wing.area_m2, p, RHO0)
    rows.append({
        "CLmax": cl,
        "Vs sea level [km/h]": sea.stall_speed() * 3.6,
        f"Vs {alt_m} m [km/h]": here.stall_speed() * 3.6,
        "launch speed needed [km/h]": here.stall_speed() * perf["launch_margin"] * 3.6,
        "endurance-limited by stall": here.stall_limited()["v_min_power"],
    })
pd.DataFrame(rows).round(1)
'''
    ),
    md("## Outputs handed to notebook 05\n"),
    code(
        '''\
aero_summary = {
    "stall_speed_m_s": vs,
    "v_best_endurance_m_s": v_endurance,
    "v_best_range_m_s": v_range,
    "cruise_drag_n": float(ac.drag_n(perf["cruise_speed_m_s"])),
    "cruise_aero_power_w": float(ac.aero_power_w(perf["cruise_speed_m_s"])),
}
aero_summary
'''
    ),
]


# ---------- 05: propulsion and endurance ---------------------------------- #

NB05 = [
    md(
        "# 05 — Propulsion and Endurance\n\n"
        "Cruise power from the drag polar, converted to pack current, then fed to\n"
        "the **same** Peukert endurance model the multirotor uses\n"
        "(`uavdesign.endurance`). Only the power-required front end differs\n"
        "between platforms.\n"
    ),
    code(bootstrap("flying_wing")),
    code(LOAD),
    code(
        '''\
from uavdesign import propulsion as prop, endurance as ed
from uavdesign.mass import MassBudget

pp, batt = design["propulsion"], design["battery"]
pack_v = batt["cells_series"] * batt["nominal_cell_v"]
battery = ed.Battery(
    capacity_ah=batt["capacity_ah"],
    nominal_voltage_v=pack_v,
    peukert_exponent=batt["peukert_exponent"],
    usable_fraction=batt["usable_fraction"],
)

# Mass from the shared budget (same build as notebook 03)
mb = MassBudget.from_yaml(
    PLATFORM_DIR / "airframe_params.yaml",
    REPO_ROOT / "payload" / "payload_manifest.yaml",
    active_payloads=design["payloads"],
    include_always_on=False,
)
mass_without_battery_g = mb.dry_mass_g
auw_kg = (mass_without_battery_g + batt["mass_g"]) * (1 + mb.contingency_fraction) / 1000
ac = FixedWingAero(auw_kg, wing.area_m2, polar, rho)

def electrical_w(aircraft, v, climb_rate=0.0):
    """Pack-side power: drag (+ climb) -> shaft -> electrical, plus avionics."""
    shaft = prop.climb_shaft_power_w(
        float(aircraft.drag_n(v)), v, aircraft.weight_n, climb_rate, pp["prop_efficiency"])
    return prop.electrical_power_w(shaft, pp["motor_efficiency"], pp["esc_efficiency"]) \\
        + pp["avionics_power_w"]

print(f"AUW from mass budget: {auw_kg*1000:.0f} g, pack {batt['cells_series']}S "
      f"{pack_v:.1f} V {batt['capacity_ah']} Ah ({battery.energy_wh:.0f} Wh)")
'''
    ),
    md("## Operating points\n"),
    code(
        '''\
import pandas as pd

vs = ac.stall_speed()
points = {
    "best endurance": (max(ac.v_min_power, 1.2 * vs), 0.0),
    "cruise": (perf["cruise_speed_m_s"], 0.0),
    "climb": (perf["climb_speed_m_s"], perf["climb_rate_m_s"]),
}
rows = []
for name, (v, roc) in points.items():
    p = electrical_w(ac, v, roc)
    i = ed.pack_current_a(p, pack_v)
    rows.append({
        "point": name, "airspeed_m_s": v, "climb_m_s": roc,
        "electrical_w": p, "pack_current_a": i, "c_rate": i / batt["capacity_ah"],
        "endurance_min": ed.endurance_min(battery, i),
    })
ops = pd.DataFrame(rows).set_index("point")
ops.round(2)
'''
    ),
    md(
        "## Motor and ESC sizing hint\n\n"
        "Size for the climb point with headroom; the cruise point decides the\n"
        "prop pitch (match pitch speed to roughly 1.3-1.5x cruise speed).\n"
    ),
    code(
        '''\
p_climb_elec = ops.loc["climb", "electrical_w"] - pp["avionics_power_w"]
print(f"Climb electrical power (propulsion): {p_climb_elec:.0f} W")
print(f"Motor continuous rating >= {1.5 * p_climb_elec:.0f} W (1.5x headroom)")
print(f"ESC continuous current  >= {1.3 * p_climb_elec / pack_v:.0f} A (1.3x headroom)")
print(f"Prop pitch speed target ~ {1.4 * perf['cruise_speed_m_s']:.0f} m/s")
'''
    ),
    md(
        "## Mission profile\n\n"
        "Climb to working height, then cruise. Segments at different currents\n"
        "share one pack via the Peukert-equivalent capacity (shared model).\n"
    ),
    code(
        '''\
climb_height_m = 120.0
v_cr, v_cl, roc = perf["cruise_speed_m_s"], perf["climb_speed_m_s"], perf["climb_rate_m_s"]
segments = [
    ed.MissionSegment("climb", climb_height_m / roc, electrical_w(ac, v_cl, roc)),
    ed.MissionSegment("cruise", perf["target_endurance_min"] * 60, electrical_w(ac, v_cr)),
]
margin = ed.mission_margin(battery, segments)
print(f"Mission: climb {climb_height_m:.0f} m, cruise {perf['target_endurance_min']} min @ {v_cr} m/s")
print(f"Usable capacity left after mission: {margin:.0%} "
      f"({'OK' if margin >= 0 else 'SHORT'}; reserve of {1 - batt['usable_fraction']:.0%} still untouched)")
'''
    ),
    md(
        "## Endurance vs battery capacity\n\n"
        "Unlike the hover sweep, a heavier pack raises wing loading and therefore\n"
        "drag *and* stall speed. Each capacity is re-flown at its own mass; the\n"
        "red region is where stall speed exceeds the limit from `design_point.yaml`.\n"
    ),
    code(
        '''\
pack_wh_per_g = battery.energy_wh / batt["mass_g"]   # baseline pack, incl. wiring
print(f"Baseline pack specific energy: {pack_wh_per_g*1000:.0f} Wh/kg")

caps = np.linspace(*batt["capacity_sweep_ah"], 40)
e_cruise, e_best, vs_arr = [], [], []
for c in caps:
    m_batt_g = c * pack_v / pack_wh_per_g
    m_kg = (mass_without_battery_g + m_batt_g) * (1 + mb.contingency_fraction) / 1000
    a = FixedWingAero(m_kg, wing.area_m2, polar, rho)
    b = ed.Battery(c, pack_v, batt["peukert_exponent"], usable_fraction=batt["usable_fraction"])
    v_best = max(a.v_min_power, 1.2 * a.stall_speed())
    e_cruise.append(ed.endurance_from_power_min(b, electrical_w(a, max(v_cr, 1.2 * a.stall_speed()))))
    e_best.append(ed.endurance_from_power_min(b, electrical_w(a, v_best)))
    vs_arr.append(a.stall_speed())

vs_arr = np.array(vs_arr)
fig, ax = plt.subplots(figsize=(7.5, 4.5))
ax.plot(caps, e_best, label="at best-endurance speed")
ax.plot(caps, e_cruise, label=f"at cruise {v_cr} m/s (or 1.2 Vs if higher)")
ax.axhline(perf["target_endurance_min"], color="grey", ls="--", lw=1, label="target")
bad = vs_arr > perf["max_stall_speed_m_s"]
if bad.any():
    ax.axvspan(caps[bad].min(), caps[-1], color="C3", alpha=0.12, label="stall speed over limit")
ax.axvline(batt["capacity_ah"], color="k", lw=0.8, ls=":")
ax.set_xlabel(f"Battery capacity [Ah, {batt['cells_series']}S]")
ax.set_ylabel("Endurance [min, reserve held back]")
ax.set_title("Endurance vs pack capacity (mass-coupled)")
ax.legend(fontsize=8)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(FIG_DIR / "05_endurance_vs_capacity.png", dpi=140)
plt.show()
'''
    ),
]


NOTEBOOKS = {
    "01_constraint_analysis.ipynb":     NB01,
    "02_geometry_and_cg.ipynb":         NB02,
    "03_mass_and_balance.ipynb":        NB03,
    "04_aero_performance.ipynb":        NB04,
    "05_propulsion_and_endurance.ipynb": NB05,
}
