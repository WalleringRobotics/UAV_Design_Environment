"""Reviewable survey-wing analysis notebooks; all design/study inputs live in YAML."""

from ._nb import bootstrap, code, md


def setup(stability=False):
    return code('''import os
for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
os.environ.setdefault("MPLCONFIGDIR", "/tmp/uavdesign-notebook-matplotlib")
''' + bootstrap("survey_wing") + f'''
import json
import pandas as pd
from IPython.display import display, Markdown, Image
from uavdesign import design as D
from uavdesign import survey as sv
from uavdesign.atmosphere import G
studies = yaml.safe_load((PLATFORM_DIR / "notebook_studies.yaml").read_text())
d = D.run(solve_stability={stability})
s = d.design["survey"]
cam = sv.Camera.from_dict(s["camera"])
pl = d.design["planform"]
req = d.design["requirements"]

def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIG_DIR / name, dpi=140)
    plt.show()
''')


NB01 = [md("""# 01 — Requirements and payload

Survey geometry bounds camera groundspeed. Aircraft stall margins constrain
airspeed; wind must be reconciled in mission planning. Figures are engineering
predictions, not flight or survey accuracy measurements. Basler is preferred and
substitutable; the existing OAK/PX4 platform remains separately supported.
"""), setup(), code('''rows = []
for factor in studies["altitude_factors"]:
    height = s["agl_m"] * factor
    rows.append({"agl_m": height, "gsd_mm_px": cam.gsd_m(height) * 1000,
                 "swath_m": cam.swath_m(height), "along_track_m": cam.footprint_along_m(height),
                 "fps_speed_limit_m_s": sv.max_ground_speed_m_s(cam, height, s["forward_overlap"]),
                 "blur_speed_limit_m_s": sv.max_speed_for_blur(cam, height, s["exposure_s"], s["blur_limit_px"])})
display(pd.DataFrame(rows))
display(pd.DataFrame([p.summary() for p in d.payloads.values()]))
'''), code('''heights = np.array(studies["altitude_factors"]) * s["agl_m"]
fig, ax = plt.subplots(figsize=(8, 4))
ax.plot(heights, [sv.max_ground_speed_m_s(cam, h, s["forward_overlap"]) for h in heights], label="Frame-rate limit (80% maximum)")
for factor in studies["exposure_factors"]:
    exposure = s["exposure_s"] * factor
    ax.plot(heights, [sv.max_speed_for_blur(cam, h, exposure, s["blur_limit_px"]) for h in heights], label=f"Blur limit at {exposure*1e6:.0f} us")
ax.set(xlabel="Height above ground [m]", ylabel="Maximum ground speed [m/s]")
ax.legend(); ax.grid(alpha=.3)
save(fig, "01_survey_speed_limits.png")
rows = []
for name, ev in d.evaluations.items():
    coverage = sv.coverage_ha(cam, s["agl_m"], ev.cruise_speed_m_s, s["side_overlap"], ev.endurance_min*60, s["turn_efficiency"])
    rows.append({"config": name, "endurance_min": ev.endurance_min, "coverage_upper_bound_ha": coverage,
                 "survey_speed_compatible": ev.survey_speed_compatible})
display(pd.DataFrame(rows))
print("Coverage uses the full estimated endurance: deduct climb, transit, return and terrain allowances for a real plan.")
from uavdesign.integration import build_handoff
handoff = build_handoff()
display(pd.DataFrame([handoff["geometry"], handoff["resources"]]))
''')]

NB02 = [md("""# 02 — Airfoil selection

NeuralFoil is a section-model screening tool. Compare at the selected design
Reynolds number and cruise lift coefficient; 3D trim, roughness and structural
thickness still determine the actual aircraft. S5010 provides a reflexed root;
E186 is the selected tip candidate and its required twist is checked with VLM in
notebook 04. A section L/D ranking alone does not select a flying-wing airfoil.
"""), setup(), code('''from uavdesign.aero import airfoil as af
re = d.selected.polar_info["reynolds"]
cl = d.selected.summary()["cl_cruise"]
summaries = [af.summarize(name, re, cl).as_dict() for name in studies["airfoil_candidates"]]
display(pd.DataFrame(summaries))
fig, axes = plt.subplots(1, 2, figsize=(11, 4))
for name in studies["airfoil_candidates"]:
    polar = af.section_polar(name, re)
    axes[0].plot(polar["cl"], polar["cd"], label=name)
    axes[1].plot(polar["cl"], polar["cm"], label=name)
axes[0].set(xlabel="Section lift coefficient", ylabel="Section drag coefficient")
axes[1].set(xlabel="Section lift coefficient", ylabel="Section pitching-moment coefficient")
for ax in axes: ax.grid(alpha=.3); ax.legend()
save(fig, "02_airfoil_comparison.png")
print(f"Selected root={pl['airfoil_root']}, tip={pl['airfoil_tip']}; Re={re:.0f}; cruise CL={cl:.3f}")
''')]

NB03 = [md("""# 03 — Sizing closure and launch alternatives

Compare the free sizing pass with the selected battery/propulsion hardware.
AR studies rebuild the sizing inputs. Hand launch remains selected; the bungee
result is a trade requiring separate structure, launch and CAD validation.
"""), setup(), code('''from dataclasses import replace
from uavdesign.sizing import size
fig, axes = plt.subplots(1, 2, figsize=(10, 4))
for label, result in (("free", d.free), ("selected", d.selected)):
    axes[0].plot(np.arange(1, len(result.history)+1), result.history, label=label)
axes[0].set(xlabel="Iteration", ylabel="All-up mass [kg]"); axes[0].legend()
axes[1].barh(list(d.selected.masses_g), list(d.selected.masses_g.values()))
axes[1].set(xlabel="Mass [g]")
save(fig, "03_closure_mass.png")
display(pd.DataFrame([{"case": "free", **d.free.summary()}, {"case": "selected", **d.selected.summary()}]))
display(pd.DataFrame([ev.__dict__ for ev in d.evaluations.values()]))
rows = []
base = D.inputs_for(d)
for aspect_ratio in studies["aspect_ratios"]:
    result = size(replace(base, aspect_ratio=aspect_ratio), auw_guess_kg=d.selected.auw_kg)
    rows.append({"aspect_ratio": aspect_ratio, "converged": result.converged,
                 "auw_kg": result.auw_kg, "span_m": result.span_m, "endurance_min": result.endurance_min})
display(pd.DataFrame(rows))
fig, ax = plt.subplots(figsize=(7, 4))
frame = pd.DataFrame(rows)
ax.plot(frame.aspect_ratio, frame.auw_kg, "o-", label="AUW")
ax.set(xlabel="Aspect ratio", ylabel="AUW [kg]")
ax2 = ax.twinx(); ax2.plot(frame.aspect_ratio, frame.endurance_min, "s--", color="C1")
ax2.set_ylabel("Endurance [min]")
save(fig, "03_aspect_ratio_trade.png")
'''), code('''uncalibrated = D.run(solve_stability=False, calibration={})
display(pd.DataFrame([{"calibration": "analytic only", **uncalibrated.selected.summary()},
                      {"calibration": "loaded CAD feedback", **d.selected.summary()}]))
display(pd.DataFrame(D.launch_trade(d)))
print("Calibration coefficients:", d.calibration)
''')]

NB04 = [md("""# 04 — Stability, trim and CG

VLM plus an empirical pod correction predicts neutral point and twist. Panknin
is an independent preliminary comparison, not a validation. Elevon trim uses
the chosen washout and real surface spans. Balance alternatives with the actual
CAD mass moment appear in notebook 07; a sizing-only run cannot establish CG.
"""), setup(True), code('''from uavdesign.aero import stability as st, airfoil as af
display(pd.DataFrame([d.stability.__dict__]))
display(pd.DataFrame([{"quarter_mac_np_mm": d.wing.x_np_mm,
                      "vlm_wing_np_mm": d.stability.x_np_wing_mm,
                      "pod_shift_mm": d.stability.x_np_wing_mm-d.stability.x_np_mm,
                      "total_np_mm": d.stability.x_np_mm, "target_cg_mm": d.x_cg_target_mm}]))
cl = d.selected.summary()["cl_cruise"]
re = d.selected.polar_info["reynolds"]
pod = (pl["pod_length_mm"], pl["pod_width_mm"])
root_polar = af.section_polar(pl["airfoil_root"], re)
root_summary = af.summarize(pl["airfoil_root"], re, cl)
a0_root = float(np.interp(0, root_polar["cl"], root_polar["alpha_deg"]))
rows = []
for tip in studies["tip_candidates"]:
    twist, result = (d.washout_deg, d.stability) if tip == pl["airfoil_tip"] else st.solve_washout(
        d.wing, pl["airfoil_root"], tip, cl, pl["static_margin"], pod=pod,
        blend_start_mm=pl["pod_width_mm"]/2)
    tip_polar = af.section_polar(tip, re)
    tip_summary = af.summarize(tip, re, cl)
    a0_tip = float(np.interp(0, tip_polar["cl"], tip_polar["alpha_deg"]))
    p = st.panknin_washout_deg(root_summary.cm_at_cl_design, tip_summary.cm_at_cl_design,
                              a0_root, a0_tip, cl, pl["static_margin"], d.wing.aspect_ratio,
                              pl["taper"], d.wing.placed_panels[0].sweep_deg_at(0.25))
    rows.append({"tip": tip, "vlm_washout_deg": twist, "panknin_washout_deg": p,
                 "neutral_point_mm": result.x_np_mm, "trim_residual_cm": result.cm0-pl["static_margin"]*cl})
display(pd.DataFrame(rows))
'''), code('''start, end = pl["elevon_span_fraction"]
model = st.WingAeroModel(pl["airfoil_root"], pl["airfoil_tip"], d.washout_deg,
                        st.ElevonSpec(start*d.wing.half_span_mm, end*d.wing.half_span_mm,
                                      1-pl["elevon_chord_fraction"]), pl["pod_width_mm"]/2)
rows = []
for margin in studies["static_margins"]:
    cg = d.stability.x_np_mm - margin*d.stability.mac_mm
    elevon, result = st.solve_elevon_trim(d.wing, model, cl, cg, pod=pod,
                                        airspeed_m_s=d.selected.cruise_speed_m_s)
    rows.append({"static_margin": margin, "cg_x_mm": cg, "elevon_deg": elevon,
                 "trim_residual_cm": result.cm_at(cl, cg)})
display(pd.DataFrame(rows))
fig, ax = plt.subplots(figsize=(7, 4))
ax.plot([r["static_margin"]*100 for r in rows], [r["elevon_deg"] for r in rows], "o-")
ax.set(xlabel="Static margin [% MAC]", ylabel="Elevon deflection [deg, negative up]"); ax.grid(alpha=.3)
save(fig, "04_trim_vs_static_margin.png")
print("Investigated CG interval [mm]:", min(r["cg_x_mm"] for r in rows), max(r["cg_x_mm"] for r in rows))
print("This is an investigated range, not a flight-approved CG envelope.")
''')]

NB05 = [md("""# 05 — Performance and battery trade

Plot electrical power above stall, cruise/climb matching constraints, and 5S1P
versus 5S2P re-flown at their own masses. Larger packs require a new physical fit
and balance check and may violate hand-launch limits on the unchanged wing.
"""), setup(), code('''from uavdesign.aero.polar import FixedWingAero
from uavdesign.aero import constraint as con
ac = FixedWingAero(d.selected.auw_kg, d.selected.wing_area_m2, d.selected.polar, d.rho)
inp = D.inputs_for(d)
speed = np.linspace(ac.stall_speed()*studies["power_speed_factors"][0],
                    d.selected.cruise_speed_m_s*studies["power_speed_factors"][1], studies["plot_points"])
efficiency = inp.prop_efficiency * inp.motor_efficiency * inp.esc_efficiency
power = ac.aero_power_w(speed)/efficiency + inp.avionics_power_w + inp.payload_power_w
fig, axes = plt.subplots(1, 2, figsize=(11, 4))
axes[0].plot(speed, power)
axes[0].axvspan(speed.min(), ac.stall_speed(), alpha=.2, color="red", label="Below stall")
axes[0].axvline(d.selected.cruise_speed_m_s, ls="--", label="Design cruise")
axes[0].set(xlabel="Airspeed [m/s]", ylabel="Electrical power [W]"); axes[0].legend()
ws = np.linspace(ac.wing_loading_n_m2*studies["wing_loading_factors"][0],
                 ac.wing_loading_n_m2*studies["wing_loading_factors"][1], studies["plot_points"])
v = d.selected.cruise_speed_m_s
for label, tw in (("Cruise", con.cruise_tw(ws,d.rho,v,ac.polar.cd0,ac.polar.k)),
                  ("Climb", con.climb_tw(ws,d.rho,v,ac.polar.cd0,ac.polar.k,req["climb_rate_m_s"]))):
    axes[1].plot(ws, con.power_per_mass_w_kg(tw,v,inp.prop_efficiency), label=label)
axes[1].axvline(con.launch_ws_max(d.rho, req["hand_launch_speed_m_s"],ac.polar.cl_max,req["launch_margin"]),ls="--",label="Hand-launch W/S maximum")
axes[1].set(xlabel="Wing loading [N/m²]",ylabel="Required shaft power [W/kg]"); axes[1].legend()
save(fig, "05_power_matching.png")
rows = D.battery_trade(d, parallels=studies["battery_parallel_counts"])
for row in rows:
    row["coverage_upper_bound_ha"] = sv.coverage_ha(cam,s["agl_m"],row["cruise_speed_m_s"],s["side_overlap"],row["endurance_min"]*60,s["turn_efficiency"])
display(pd.DataFrame(rows))
fig, axes = plt.subplots(1,2,figsize=(9,4))
for ax, key, label in ((axes[0],"endurance_min","Endurance [min]"),(axes[1],"coverage_upper_bound_ha","Survey coverage upper bound [ha]")):
    ax.bar([r["pack"] for r in rows],[r[key] for r in rows]); ax.set_ylabel(label)
save(fig,"05_pack_trade.png")
''')]

NB06 = [md("""# 06 — Structure and controls

Schrenk-like lift loading, no inertia relief, and a declared safety factor screen
the carbon tubes. These checks omit joint/adhesive failure, local print strength,
buckling and fatigue. Servo torque uses the documented RC empirical rule with
an explicit margin; bench linkage loads remain required.
"""), setup(), code('''from uavdesign import structures as struct
from uavdesign.fab.geometry import WingGeometry, spar_layout
spar = d.design["structure"]["spars"]
geometry = WingGeometry.from_airframe(D.airframe_geometry(d))
layout = spar_layout(geometry,spar,pl["pod_width_mm"]/2)
stations = np.linspace(0,d.wing.half_span_mm,studies["plot_points"])
moments = np.array([struct.root_bending_moment_n_mm(d.selected.auw_kg*G,d.wing.half_span_mm,
                  req["load_factor_limit"], y,pl["taper"])*req["safety_factor"] for y in stations])
rows = []
fig, axes = plt.subplots(1,2,figsize=(11,4))
axes[0].plot(stations,moments,label="Factored bending moment")
for name, station in (("joiner",0),("sleeve",pl["pod_width_mm"]/2),
                      ("outer_spar",spar["outer_spar"]["y_start_fraction"]*d.wing.half_span_mm)):
    tube = struct.Tube(spar[name]["od_mm"],spar[name]["id_mm"],spar["density_g_cm3"],spar["allowable_mpa"],spar["modulus_gpa"])
    check = struct.check_spar(tube,d.selected.auw_kg*G,d.wing.half_span_mm,req["load_factor_limit"],req["safety_factor"],station,pl["taper"])
    rows.append({"tube":name,**check.__dict__})
    capacity=tube.allowable_mpa*tube.second_moment_mm4/(tube.od_mm/2)
    axes[0].axhline(capacity,ls="--",label=f"{name} section capacity")
axes[0].set(xlabel="Span station [mm]",ylabel="Moment [N mm]");axes[0].legend()
ys = np.linspace(0,d.wing.half_span_mm,studies["plot_points"])
axes[1].plot(ys,[geometry.le_x(y) for y in ys],color="black")
axes[1].plot(ys,[geometry.le_x(y)+geometry.chord(y) for y in ys],color="black")
for name in ("joiner","sleeve","outer","rear_pin"):
    path=getattr(layout,name)
    axes[1].plot([path.p0[1],path.p1[1]],[path.p0[0],path.p1[0]],label=name)
axes[1].invert_yaxis();axes[1].set(xlabel="Span [mm]",ylabel="x aft [mm]");axes[1].legend()
save(fig,"06_spars.png")
display(pd.DataFrame(rows));display(layout.checks)
screen=studies["servo_screen"]
start,end=pl["elevon_span_fraction"]
surface_chord=float(d.wing.chord_at((start+end)/2*d.wing.half_span_mm))*pl["elevon_chord_fraction"]
torque=struct.servo_torque_kg_cm(surface_chord,(end-start)*d.wing.half_span_mm,
        d.selected.cruise_speed_m_s,screen["surface_deflection_deg"],screen["servo_deflection_deg"])
display(pd.DataFrame([{"required_with_margin_kg_cm":torque*screen["torque_margin"],
                      "rated_kg_cm":screen["rated_torque_kg_cm"],
                      "pass":torque*screen["torque_margin"]<=screen["rated_torque_kg_cm"],
                      "status":screen["status"]}]))
''')]

NB07 = [md("""# 07 — Fabrication and physical balance

This notebook reads the current CAD export. If it is absent, run the printed
command and reopen the notebook. It never substitutes analytic geometry for a
missing part build. Inspect preview images, calibration agreement, printer fit
and both balance alternatives before selecting a mechanical revision.
"""), setup(True), code('''manifest_path=REPO_ROOT/"outputs/parts/manifest.json"
manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else None
if manifest is None:
    print("No parts manifest. Run: python scripts/build_parts.py")
else:
    display(pd.DataFrame(manifest["parts"]))
    display(pd.DataFrame([manifest["balance"]]))
    print("Manifest sizing summary:",manifest.get("design",manifest.get("sizing",{})))
'''), code('''if manifest is not None:
    parts=pd.DataFrame(manifest["parts"])
    if "mass_g" in parts and "group" in parts:
        display(parts.groupby("group")["mass_g"].sum().rename("cad_printed_mass_g").to_frame())
    display(pd.Series(d.selected.masses_g,name="sizing_mass_g").to_frame())
    for path in sorted(manifest_path.parent.glob("preview*.png")):
        display(Markdown(f"### {path.name}"));display(Image(filename=str(path)))
    balance=manifest["balance"]
    fig,ax=plt.subplots(figsize=(9,3))
    for name,key in (("CG","cg_x_mm"),("Neutral point","x_np_mm"),("Battery","battery_x_mm")):
        if key in balance: ax.axvline(balance[key],label=f"{name}: {balance[key]:.1f} mm")
    ax.axvline(d.x_cg_target_mm,color="black",ls="--",label="Sizing target CG")
    ax.set(xlabel="x aft of root leading edge [mm]",yticks=[]);ax.legend()
    save(fig,"07_balance.png")
    if "contingency_g" in balance:
        display(pd.DataFrame(D.balance_alternatives(d,balance)))
    else:
        print("Legacy balance lacks contingency_g: rebuild parts before comparing alternatives.")
''')]

NB08 = [md("""# 08 — Electronics, propulsion and thermal integration

The BOM keeps source/provenance/confirmation fields visible. Average rail loads
do not qualify transients. CT/CP propeller screening is an estimate, not measured
thrust, and a nominal voltage pass does not establish low-pack launch margin.
Survey software integration is exported separately; the existing OAK/PX4
platform and new ArduPilot wing remain distinct.
"""), setup(), code('''display(pd.DataFrame(d.electronics.bom_rows()))
display(pd.DataFrame([p.summary() for p in d.payloads.values()]))
rows=[]
for config,payload in d.payloads.items():
    tree=d.electronics.power_tree(D.payload_loads_w(payload))
    for rail,load in tree.items():
        if isinstance(load,dict): rows.append({"config":config,"rail":rail,**load})
rails=pd.DataFrame(rows);display(rails)
fig,ax=plt.subplots(figsize=(10,4))
rails.dropna(subset=["utilisation"]).pivot(index="rail",columns="config",values="utilisation").plot.bar(ax=ax)
ax.axhline(1,color="red",ls="--");ax.set(ylabel="Nominal current / rail capacity",xlabel="Power rail")
save(fig,"08_rail_utilisation.png")
print("Open hardware items:")
for item in d.electronics.open_items(): print("-",item)
for name,p in d.payloads.items():
    if p.compute.get("confirm"): print(f"- {name}: {p.compute['confirm']}")
for name,item in next(iter(d.payloads.values())).cage_members.items():
    if item.get("confirm"):print(f"- {name}: {item['confirm']}")
'''), md('''## Wiring responsibilities

```mermaid
flowchart LR
  Battery --> ESC --> Motor
  Battery --> FC[ArduPilot flight controller]
  FC --> FlightGNSS[Independent flight GNSS]
  Battery --> ServoReg[Servo regulator] --> Elevons
  Battery --> ComputeReg[Compute regulator] --> Companion[Orin or CM5]
  FC --> CameraPower[Camera rail]
  CameraPower --> Camera[Preferred GigE camera]
  Camera -->|Ethernet images| Companion
  Camera -->|Isolated exposure event| SurveyGNSS[F9P survey receiver]
  SurveyGNSS -->|Raw observations and event marks| Companion
  FC <-->|MAVLink telemetry| Companion
  Companion --> NVMe
```

Pin assignments, signal voltages, ground/shield strategy and regulator transient
ratings require the final carrier/receiver/camera choices and harness bench checks.
'''), code('''screen=D.propulsion_checks(d)
display(pd.DataFrame(screen["checks"]));display(screen["assumptions"])
display(pd.DataFrame([D.thermal_report(d)]))
print(screen["status"])
from uavdesign.integration import build_handoff,validate_handoff
display(validate_handoff(build_handoff()))
''')]

NOTEBOOKS = {
    "01_requirements_and_payload.ipynb": NB01,
    "02_airfoil_selection.ipynb": NB02,
    "03_sizing_closure.ipynb": NB03,
    "04_stability_and_trim.ipynb": NB04,
    "05_performance.ipynb": NB05,
    "06_structures.ipynb": NB06,
    "07_fabrication.ipynb": NB07,
    "08_electronics.ipynb": NB08,
}
