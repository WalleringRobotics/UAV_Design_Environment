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
from dataclasses import replace
acquisition_cam = replace(cam, max_fps=min(cam.max_fps, s["acquisition_rate_cap_hz"]))
pl = d.design["planform"]
req = d.design["requirements"]

def save(fig, name):
    fig.tight_layout()
    path = FIG_DIR / name
    fig.savefig(path, dpi=140)
    display(Image(filename=str(path)))
    plt.close(fig)
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
ax.plot(heights, [sv.max_ground_speed_m_s(cam, h, s["forward_overlap"]) for h in heights], label="Camera frame-rate limit (80% maximum)")
ax.plot(heights, [sv.max_ground_speed_m_s(acquisition_cam, h, s["forward_overlap"]) for h in heights], "--", label="Acquisition cap (80% of configured cap)")
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


# These narrative cells are kept with the executable definitions so the checked-in
# notebooks and the review export share one explanation of the model boundaries.
NB01.insert(1, md(r"""## Derivation and decision boundary

**Inputs:** `design_point.yaml: survey`, `mission/mission_params.yaml`,
`payload/survey_cage.yaml`. **Implementation:** `uavdesign/survey.py`,
`design.survey_speed_limit`, and `integration.resource_budget`.

For nadir viewing over level ground, with height $H$ [m], pixel pitch $p$ [m],
focal length $f$ [m], and image dimensions $N_x,N_y$ [pixels]:

$$g=Hp/f,\quad W=N_xg,\quad L=N_yg,\quad d=L(1-o_f)$$
$$f_{trigger}=V_g/d,\quad b_{px}=V_g t_e/g,\quad
V_{g,max}=\min(0.8 f_{cap}d,\;b_{max}g/t_e).$$

Plain-text equations: `GSD = height * pixel_pitch / focal_length`;
`trigger_spacing = image_length * (1 - forward_overlap)`;
`trigger_hz = groundspeed / trigger_spacing`; `blur_px = groundspeed * exposure / GSD`.

Here $g$ is GSD [m/pixel], $d$ trigger spacing [m], $o_f$ forward overlap,
$t_e$ exposure [s], and $V_g$ **groundspeed** [m/s]. The camera's maximum FPS
and the selected acquisition cap are distinct; both appear in the plot. The
0.8 frame-rate multiplier reserves timing headroom. Side overlap controls line
spacing $W(1-o_s)$, not forward triggering. Coverage uses that spacing, speed,
survey time and the configured on-line fraction; its upper bound does not include
transit or return allocations.

**External review:** establish the actual lens focus/distortion, exposure-event
latency and sustained image rate. GSD is sampling distance, not demonstrated
position accuracy. Terrain, oblique attitude, crosswind crab and rolling mission
altitude require a footprint model beyond this flat-ground calculation.
"""))
NB02.insert(1, md(r"""## What the airfoil comparison establishes

**Inputs:** `planform` in `design_point.yaml` and `airfoil_candidates` in
`notebook_studies.yaml`. **Implementation:** `uavdesign/aero/airfoil.py`
(NeuralFoil section predictions), then `uavdesign/aero/polar.py` (aircraft drag).

The design Reynolds number is $Re=\rho Vc/\mu=Vc/\nu$; the implementation uses
`Re = speed * chord / nu` with the declared constant kinematic viscosity
`NU_AIR = 1.5e-5 m2/s`, rather than a temperature-dependent viscosity model.
Here $c$ is the model reference
chord, not every local wing chord. Section $c_l,c_d,c_m$ are dimensionless.
The aircraft requires $C_L=2mg/(\rho V^2S)$, while the local section lift varies
across the span. A section evaluated at aircraft $C_L$ is a comparison point,
not a spanwise load solution. The selected sizing polar applies the declared
3D lift, trim, roughness and miscellaneous-drag corrections.

Root reflex supports tailless trim; the tip choice also changes twist and load
distribution. The VLM comparison in notebook 04 is therefore necessary before
interpreting a favorable section $c_l/c_d$ as an aircraft improvement.

**External review:** repeat the section screen over local Reynolds number and
surface-condition ranges; inspect stall confidence and transition assumptions.
No wind-tunnel result, measured printed roughness, or full-aircraft stall test is
present. A plotted neural-model curve is not a measured polar.
"""))
NB03.insert(1, md(r"""## Mass closure and dependency chain

**Inputs:** `design_point.yaml`, `electronics.yaml`, payload YAML and generated
`calibration.yaml`. **Implementation:** `uavdesign/sizing.py` and
`design.inputs_for`. The shared mission supplies air density conditions.

The mass loop is $m_{k+1}=m_{payload}+m_{avionics}+m_{structure}(S_k,b_k)
+m_{propulsion}+m_{battery}+m_{contingency}$. Hand-launch sizing imposes
$V_{release}\geq M_{launch}V_s$, with
$V_s=\sqrt{2mg/(\rho S C_{L,max})}$; span then follows
$b=\sqrt{AR\,S}$. These equations explain why payload, effective $C_{L,max}$
and launch assumptions can grow both structure and wing area.

Plain-text equations: `stall_speed = sqrt(2 * mass * g / (density * area * CLmax))`;
`span = sqrt(aspect_ratio * area)`; `next_mass = sum(component_mass_estimates)`.

The free pass estimates propulsion and battery continuously. The selected pass
uses the discrete BOM masses and pack energy, so achieving mass convergence does
not guarantee the endurance target. The AR trade re-sizes each candidate rather
than stretching one completed CAD model; its results are not fabrication files.

`calibration.yaml: measured` contains **CAD-derived estimates**, not scale
measurements. CAD surface/volume plus assumed density, perimeters and infill
correct the analytic mass model. Agreement between two models sharing those
assumptions is consistency evidence, not physical validation.

**External review:** inspect convergence, mass contingency allocation and payload
interchangeability. Repeat with weighed coupons and hardware; re-check structure,
fit and balance for every candidate retained after the trade.
"""))
NB04.insert(1, md(r"""## Reference frame, trim and sensitivity

**Inputs:** `planform`, section-model outputs, and study ranges. **Implementation:**
`uavdesign/aero/stability.py`. Aircraft coordinates are millimetres: $x$ aft of
the root leading edge, $y$ right, $z$ up. Angles in the tables are degrees.

Static margin is $SM=(x_{NP}-x_{CG})/\bar c$, where $\bar c$ is MAC. A positive
margin puts CG forward of the predicted neutral point. The model's moment
relation is $C_m(C_L,x_{CG})=C_{m,0}-SM C_L$; the washout solve brackets a root
of that expression at the target margin. The elevon solve uses actual span and
hinge fractions, and rejects a trim demand outside its solver bracket.

Plain-text equations: `static_margin = (neutral_point_x - CG_x) / MAC`;
`Cm_at_CG = Cm0 - static_margin * CL`; trim requires `Cm_at_CG = 0`.

VLM describes attached-flow loading; section viscous drag and stall do not
emerge from that solution. The empirical pod neutral-point correction introduces
additional uncertainty. Panknin is a different preliminary formulation but shares
section inputs, so agreement is not an independent experiment. The generated CAD
adds finite trailing-edge thickness and manufacturing detail to the aerodynamic
section representation.

**External review:** compare target CG with the manifest's realizable balance,
then assess trim at that CG, control authority, pitch damping and stall behavior.
A range with converged trim roots is not an approved flight envelope. Notebook 09
shows the battery-position lever arm without claiming a new trim qualification.
"""))
NB05.insert(1, md(r"""## Power and endurance accounting

**Inputs:** selected wing/polar, pack and propulsion efficiency assumptions,
requirements and payload rail loads. **Implementation:** `uavdesign/aero/polar.py`,
`uavdesign/endurance.py`, `uavdesign/sizing.py`, `design.battery_trade`.

With $q=\rho V^2/2$, the drag model is
$D=qS(C_{D0}+kC_L^2)$ and aerodynamic power is $DV$ [W]. Electrical input is
$P_e=DV/(\eta_p\eta_m\eta_{ESC})+P_{hotel}$, where $P_{hotel}$ includes the
modeled avionics and payload loads. The endurance function applies usable battery
energy and the configured Peukert correction; nominal $E/P_e$ alone is not its
complete result. The vertical stall marker bounds the usefulness of the smooth
attached-flow power curve.

Plain-text equations: `drag = 0.5 * density * speed^2 * area * (CD0 + k*CL^2)`;
`electrical_power = drag * speed / (prop_eff * motor_eff * ESC_eff) + hotel_power`.

Each 5S pack candidate changes aircraft mass and is evaluated on the fixed
baseline wing. More electrical energy also raises stall speed and structural load;
there is no CAD or handling approval implicit in the battery table. Coverage again
uses the estimated full-duration upper bound from notebook 01.

**External review:** establish propulsive efficiency versus airspeed, minimum-pack
thrust/current, cell temperature and voltage sag. Allocate climb, transit and
return energy before using any duration as survey time. The nominal sizing target
and actual discrete-pack prediction should both remain visible.
"""))
NB06.insert(1, md(r"""## Structural load path and what remains unchecked

**Inputs:** `structure.spars`, load factor, safety factor, aircraft mass and taper.
**Implementation:** `uavdesign/structures.py` and `fab.geometry.spar_layout`.

For a hollow circular tube, $I=\pi(D_o^4-D_i^4)/64$ [mm$^4$], bending stress
$\sigma=Mc/I$ [MPa when $M$ is N mm], and nominal section capacity is
$M_{allow}=\sigma_{allow}I/c$. The plotted bending load integrates the declared
spanwise lift screen at the limit load factor, then multiplies by the safety
factor. It takes no inertia relief and does not resolve a landing impact pulse.

Plain-text equations: `I = pi * (OD^4 - ID^4) / 64`;
`bending_stress = moment * (OD/2) / I`; compare stress [MPa] with the assumed allowable.

The straight joiner transfers loads through the pod and bonded sleeves; the swept
outer spars overlap that path. A section stress pass does **not** qualify overlap
length, bond peel/shear, the printed spar box, local bearing, tube crushing,
wing torsion, flutter, or a jammed control. Carbon tube allowable and modulus are
input assumptions, not supplier batch acceptance results.

**External review:** reconcile stiffness and load sharing across joiner/sleeve/outer
spar intersections. Define representative bonded-joint and printed-coupon tests
using actual layer direction and environmental conditioning. Inspect the servo
calculation's empirical torque convention, linkage arm ratio, travel, hinge gaps
and installed operating voltage before using its nominal margin.
"""))
NB07.insert(1, md(r"""## CAD evidence versus analytic geometry

**Inputs:** current `outputs/parts/manifest.json` and exported meshes/STEP files.
**Implementation:** `uavdesign/fab/build.py`, airframe/cage generators and shared
`fab/geometry.py`. Manufacturing settings are in `fabrication.yaml`.

The analytic wing defines planform, airfoil blend and twist. The CAD build adds
shell walls, finite trailing edges, print splits, joiner paths, clearances,
cutouts and purchased-component envelopes. Assembly STEP is in the aircraft
frame ($x$ aft, $y$ right, $z$ up); each print STL has its own bed-oriented frame.
Never infer an assembled location from the STL's print coordinates.

The manifest mass entries estimate deposited material and hardware masses.
They are **not measured finished-part weights or slicer-consumption estimates**.
The balance calculation uses $x_{CG}=\sum m_i x_i/\sum m_i$ with the declared
component locations. Battery positions must satisfy both the allowed envelope
and installed-component interference checks. A target marked unreachable must
remain an open design issue even when all parts individually fit the printer.

Plain-text equation: `CG_x = sum(component_mass * component_x) / sum(component_mass)`.

**External review:** compare the preview, assembly and source dimensions; inspect
bonding access, connector routing, screw access, retention, cooling and actual
vendor envelope tolerances. Notebook 10 hashes the current files and reports
manufacturing evidence; a hash confirms identity, not strength or printability.
"""))
NB08.insert(1, md(r"""## Hardware and software interfaces

**Inputs:** `electronics.yaml`, `payload/survey_cage.yaml`, `design_point.yaml`
and `integration/mapping_profile.yaml`. **Implementation:** `electronics.py`,
`payload.py`, `propulsion.py`, `power.py` and `integration.py`.

Rail current is modeled from average consumer power divided by rail voltage;
regulator loss propagates back to the pack. Rated-current utilization is a useful
budget comparison but does not include servo stalls, compute start-up, cable loss
or camera transients unless separately declared. Static propeller screening uses
$T=C_T\rho n^2D^4$ and $P=C_P\rho n^3D^5$, with $n$ in revolutions/s and $D$ in
metres. The numerical coefficients and loaded-RPM fraction are assumed. Cooling
uses $\dot m=P_{heat}/(c_p\Delta T)$; aperture sizing is not a pressure-drop or
component-temperature prediction.

Plain-text equations: `thrust = CT * density * rev_per_second^2 * diameter^4`;
`shaft_power = CP * density * rev_per_second^3 * diameter^5`;
`cooling_mass_flow = heat / (specific_heat * temperature_rise)`.

The dedicated fixed-wing build uses a Basler-preferred camera and ArduPilot Plane.
The existing OAK/PX4 multirotor stays a separate supported platform. The exported
mapping handoff describes required capture, timing, navigation and resource
contracts; it does not assert that the adjacent repository already implements
those adapters. The inspection revisions recorded in the handoff bound that claim.

**External review:** resolve BOM confirmation fields, rail protection, isolated
trigger/event timing, sensor and body frames, optical-centre and antenna offsets,
raw GNSS association, storage endurance and thermal soak. Follow source links in
the BOM to verify the chosen revision; no online refresh or procurement is
performed by executing this notebook.
"""))

NB09 = [md(r"""# 09 — Mission constraints and physical-balance sensitivity

This notebook exposes interactions hidden by a single design-point number. It
recomputes mission geometry from YAML and cross-checks selected outputs with
simple equations. It reads current CAD balance if present; it does not create a
new approved configuration or silently resize the aircraft.
"""), setup(), md(r"""## Wind changes ground speed independently of stall margin

For a straight commanded ground track, let $w_\parallel$ be wind along that track
(tailwind positive) and $w_\perp$ its crosswind component. At true airspeed $V_a$,
heading correction gives
$$V_g=\sqrt{V_a^2-w_\perp^2}+w_\parallel.$$
Plain-text equation: `groundspeed = sqrt(airspeed^2 - crosswind^2) + tailwind`.
A real positive root requires $|w_\perp|<V_a$ and forward progress requires $V_g>0$.
At fixed airspeed, a tailwind can violate image blur or frame-rate limits while a
headwind reduces progress. The angle below is the **wind velocity vector relative
to the track**, not a meteorological wind-from bearing. The plot uses the mission's
maximum wind and the study altitude factors; it does not set a flight wind limit.
"""), code('''max_wind = float(d.mission["mission"]["max_wind_speed_ms"])
v_air = d.selected.cruise_speed_m_s
v_stall = d.selected.stall_speed_m_s
angles = np.linspace(0, 360, studies["plot_points"] * 4 + 1)
wind_rows = []
fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
for fraction in [0.0, 1.0]:
    wind = max_wind * fraction
    along = wind * np.cos(np.radians(angles))
    cross = wind * np.sin(np.radians(angles))
    ground = np.where(abs(cross) < v_air,
                      np.sqrt(np.maximum(0, v_air**2-cross**2)) + along, np.nan)
    axes[0].plot(angles, ground, label=f"Wind {wind:.1f} m/s")
axes[0].axhline(d.survey_speed_limit_m_s, ls="--", color="C3", label="Nominal imaging speed ceiling")
axes[0].set(xlabel="Wind vector relative to track [deg; 0 = tailwind]", ylabel="Groundspeed at design airspeed [m/s]")
for case, parallel, perpendicular in (("headwind", -max_wind, 0), ("crosswind", 0, max_wind), ("tailwind", max_wind, 0)):
    ground = np.sqrt(v_air**2-perpendicular**2) + parallel if abs(perpendicular) < v_air else np.nan
    wind_rows.append({"case": case, "airspeed_m_s": v_air, "groundspeed_m_s": ground,
                      "trigger_hz": sv.trigger_rate_hz(cam, s["agl_m"], ground, s["forward_overlap"]),
                      "motion_blur_px": sv.blur_px(cam, s["agl_m"], ground, s["exposure_s"]),
                      "within_imaging_ceiling": bool(0 < ground <= d.survey_speed_limit_m_s)})
heights = np.asarray(studies["altitude_factors"]) * s["agl_m"]
limits = np.array([min(sv.max_ground_speed_m_s(acquisition_cam, h, s["forward_overlap"]),
                      sv.max_speed_for_blur(cam, h, s["exposure_s"], s["blur_limit_px"])) for h in heights])
axes[1].plot(heights, limits-v_air, "o-", label="Tailwind ceiling at design cruise")
axes[1].plot(heights, limits-v_stall*req["launch_margin"], "s--", label="At launch-margin × stall (reference only)")
axes[1].axhline(max_wind, color="C3", ls=":", label="Mission maximum wind")
axes[1].axhline(0, color="black", lw=.7)
axes[1].set(xlabel="AGL [m]", ylabel="Allowable along-track tailwind from imaging [m/s]")
for ax in axes: ax.legend(fontsize=8); ax.grid(alpha=.25)
save(fig, "09_wind_and_imaging.png")
display(pd.DataFrame(wind_rows))
print("The launch margin is shown only as a reference airspeed, not a qualified survey-speed control law.")
'''), md(r"""## Small changes around the selected point

At constant mass and wing, $V_s\propto\sqrt{m}$ and
$\partial x_{CG}/\partial x_{battery}=m_{battery}/m_{aircraft}$. At fixed pack and
electrical load shape, reserve allocations reduce usable survey time. The figure
below keeps the existing endurance model result and subtracts explicit mission-time
allocations; these allocations are a sensitivity sweep from zero to the configured
turn-time fraction, **not** measured transit times. The original turn efficiency is
still applied within the remaining survey window, avoiding double-counting it as
available on-line time.

Plain-text equations: `CG_shift = pack_mass / aircraft_mass * pack_position_shift`;
`survey_time = predicted_endurance * (1 - extra_time_allocation)`.
Coverage uses cruise airspeed as a calm-wind groundspeed reference; real wind
and separate climb/transit power demands require a segment-by-segment mission model.
"""), code('''fractions = np.linspace(0, 1-s["turn_efficiency"], studies["plot_points"])
fig, ax = plt.subplots(figsize=(8, 4))
for name, ev in d.evaluations.items():
    remaining = ev.endurance_min * (1-fractions)
    coverage = [sv.coverage_ha(cam, s["agl_m"], ev.cruise_speed_m_s, s["side_overlap"], t*60, s["turn_efficiency"]) for t in remaining]
    ax.plot(fractions*100, coverage, label=f"{name}: estimated full duration {ev.endurance_min:.1f} min")
ax.set(xlabel="Additional flight time allocated outside survey [%]", ylabel="Remaining survey coverage upper bound [ha]")
ax.legend(); ax.grid(alpha=.25)
save(fig, "09_coverage_allocation.png")
manifest_path = REPO_ROOT / "outputs/parts/manifest.json"
manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
if manifest is None:
    print("No CAD balance available: build parts before the physical-balance sensitivity review.")
else:
    balance = manifest["balance"]
    fab = yaml.safe_load((PLATFORM_DIR / "fabrication.yaml").read_text())
    total = balance["auw_g"]
    pack_mass = d.electronics.pack.mass_g
    fig, ax = plt.subplots(figsize=(9, 4))
    for bay in fab["layout"]["battery_placements"]:
        xs = np.linspace(*bay["cg_range_mm"], studies["plot_points"])
        cg = balance["cg_x_mm"] + pack_mass/total * (xs-balance["battery_x_mm"])
        sm = (balance["x_np_mm"]-cg)/manifest["design"]["mac_mm"]
        ax.plot(xs, 100*sm, label=f"{bay['name']} envelope; all other masses fixed")
    ax.axhline(100*pl["static_margin"], color="black", ls="--", label="Design target")
    ax.scatter([balance["battery_x_mm"]], [100*balance["static_margin"]], color="C3", label="Current CAD balance", zorder=5)
    ax.set(xlabel="Battery CG x aft of root LE [mm]", ylabel="Predicted static margin [% MAC]")
    ax.legend(fontsize=8); ax.grid(alpha=.25)
    save(fig, "09_battery_position_sensitivity.png")
    display(pd.DataFrame([{"aircraft_mass_g":total, "pack_mass_g":pack_mass,
                           "cg_movement_per_mm_pack_movement":pack_mass/total,
                           "target_reachable_in_current_build":balance["target_cg_reachable"]}]))
    print("Aft-bay points are moment sensitivities only. They do not prove installed fit, trim authority or an acceptable static margin.")
'''), md(r"""## Independent arithmetic and reviewer questions

The following checks use direct equations rather than calling the corresponding
survey/wing model helper. They can expose a units or stale-output mistake, but
still share the input assumptions and therefore are not independent experimental
validation. Review the wind conflict, discrete-pack endurance shortfall, and
unreachable baseline CG as design decisions; do not suppress them because an
individual model or mesh export passed.
"""), code('''summary = d.selected.summary()
independent_area = .5*(d.wing.root_chord_mm+d.wing.tip_chord_mm)*(2*d.wing.half_span_mm)/1e6
independent_gsd = s["agl_m"] * s["camera"]["pixel_um"]*1e-6 / (s["camera"]["focal_mm"]*1e-3)
checks = [
    {"quantity":"Trapezoidal wing area [m2]", "direct_equation":independent_area, "model_result":d.selected.wing_area_m2},
    {"quantity":"Aspect ratio [-]", "direct_equation":d.selected.span_m**2/independent_area, "model_result":pl["aspect_ratio"]},
    {"quantity":"GSD [m/pixel]", "direct_equation":independent_gsd, "model_result":cam.gsd_m(s["agl_m"])},
    {"quantity":"Cruise CL [-]", "direct_equation":2*d.selected.auw_kg*G/(d.rho*d.selected.cruise_speed_m_s**2*independent_area), "model_result":summary["cl_cruise"]},
]
for row in checks:
    row["absolute_difference"] = abs(row["direct_equation"]-row["model_result"])
display(pd.DataFrame(checks))
requirements = [
    {"review_item":"Launch release / stall", "prediction":req["hand_launch_speed_m_s"]/v_stall, "bound":req["launch_margin"], "comparison":">=", "model_pass":req["hand_launch_speed_m_s"] >= req["launch_margin"]*v_stall},
    {"review_item":"Selected payload endurance [min]", "prediction":d.selected.endurance_min, "bound":req["endurance_min"], "comparison":">=", "model_pass":d.selected.endurance_min >= req["endurance_min"]},
    {"review_item":"Cruise + maximum tailwind [m/s]", "prediction":v_air+max_wind, "bound":d.survey_speed_limit_m_s, "comparison":"<=", "model_pass":v_air+max_wind <= d.survey_speed_limit_m_s},
]
display(pd.DataFrame(requirements))
print("Model pass is only the listed arithmetic comparison; no flight authorization or hardware qualification is implied.")
''')]

NB10 = [md(r"""# 10 — Manufacturing evidence and external-review audit

This is the review entry point for parts, printing and provenance. It reads the
current export, shows what can be independently checked offline, and separates
estimated mass, geometric fit, arranged beds, slicing and physical validation.
Missing evidence remains visible. No printer connection, upload or print start
is performed.
"""), setup(), md(r"""## Reproduction and evidence identity

Source inputs live in versioned YAML; the tables below fingerprint the exact
inputs loaded for this run. The implementation hash map is also retained by the
`Design` result and exported with the dossier. The generated calibration record's
`measured` label means CAD-derived mass, **not scale measurements**.

For a fresh environment, install the repository's locked dependencies, run
`python scripts/build_parts.py`, then `python -m uavdesign.printing plan`.
Execute notebooks from their platform directory or the repository root. The
review exporter preserves executed notebooks and embedded figures so a reader
can inspect the findings without installing CAD software. Re-running the code
still requires the declared Python dependencies and source tree.

A SHA-256 match proves that a file is the same file recorded by a manifest. It
cannot prove that a model represents the physical aircraft. The CAD manifest's
result signature is displayed as identity evidence; dimensions and masses below
are cross-checks rather than a claim of complete source-to-CAD provenance.
"""), code('''import hashlib
fingerprints = [{"input_file": name, "sha256": sha} for name, sha in sorted(d.input_hashes.items())]
display(pd.DataFrame(fingerprints))
print("Implementation Python files fingerprinted:", len(d.source_hashes))
manifest_path = REPO_ROOT / "outputs/parts/manifest.json"
manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
if manifest is None:
    print("No parts manifest. Run: python scripts/build_parts.py")
else:
    print("Manifest SHA-256:", hashlib.sha256(manifest_path.read_bytes()).hexdigest())
    print("CAD result signature:", manifest["result_signature"])
    print("CAD maturity:", manifest["maturity"])
    hashes = []
    for relative, expected in sorted(manifest["file_sha256"].items()):
        path = (manifest_path.parent / relative).resolve()
        inside = path.is_relative_to(manifest_path.parent.resolve())
        exists = inside and path.is_file()
        hashes.append({"file":relative, "present":exists,
                       "sha256_matches":exists and hashlib.sha256(path.read_bytes()).hexdigest() == expected})
    hash_frame = pd.DataFrame(hashes)
    display(hash_frame.groupby(["present", "sha256_matches"]).size().rename("file_count").to_frame())
    if not hash_frame["sha256_matches"].all():
        display(hash_frame[~hash_frame["sha256_matches"]])
        raise ValueError("CAD files failed manifest identity checks; review cannot use them as a coherent export")
'''), md(r"""## Scale, manufacturing estimates and design consistency

The printer envelope is a build-volume constraint; the assembled span is a
separate aircraft dimension. Pieces are split along span and sometimes chord to
fit while preserving layer direction. The part-height chart indicates tall prints,
not stability on the bed, cooling adequacy or print duration.

Mass by profile comes from CAD deposition assumptions. Supports, brim, waste,
adhesive, process-dependent foaming and hardware tolerances require separate
accounting. Nominal wall thickness is perimeters times extrusion width; actual
thin-wall toolpaths must be inspected in the slicer. The source STL envelope,
assembly geometry and finished-part dimension are three different kinds of data.
"""), code('''if manifest is not None:
    parts = pd.DataFrame(manifest["parts"])
    display(parts[["part", "group", "profile", "material", "mass_g", "footprint_mm", "height_mm", "fits"]])
    groups = parts.groupby("profile").agg(parts=("part", "size"), mass_estimate_g=("mass_g", "sum"), tallest_mm=("height_mm", "max"))
    display(groups)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    groups["mass_estimate_g"].sort_values().plot.barh(ax=axes[0], color="C0")
    axes[0].set(xlabel="Estimated deposited part mass [g]", ylabel="Print profile")
    for index, (profile, frame) in enumerate(parts.groupby("profile")):
        axes[1].scatter([index]*len(frame), frame.height_mm, s=35, label=profile)
    axes[1].axhline(manifest["printer"]["max_z_mm"], ls="--", color="C3", label="Printer height limit")
    axes[1].set(xticks=range(len(groups)), xticklabels=list(groups.index), ylabel="Print-oriented height [mm]")
    axes[1].tick_params(axis="x", rotation=50)
    axes[1].grid(axis="y", alpha=.25)
    save(fig, "10_manufacturing_scale.png")
    reference = D.airframe_geometry(d)
    # solve_stability=False supplies placeholder trim, so exclude trim/NP/CG here.
    geometry_keys = ["root_chord_mm", "tip_chord_mm", "half_span_mm", "le_sweep_deg", "pod_width_mm", "pod_height_mm", "pod_length_mm"]
    geometry_checks = [{"quantity":key, "current_analytic_input":reference[key], "CAD_recorded":manifest["design"][key],
                        "difference":manifest["design"][key]-reference[key]} for key in geometry_keys]
    display(pd.DataFrame(geometry_checks))
    display(pd.DataFrame([{"sizing_mass_g":d.selected.auw_kg*1000, "CAD_balance_mass_g":manifest["balance"]["auw_g"],
                           "difference_percent":100*(manifest["balance"]["auw_g"]/(d.selected.auw_kg*1000)-1),
                           "printed_mass_estimate_g":parts.mass_g.sum()}]))
    print("CAD geometry is rounded in the manifest. Agreement is expected within export precision, not exact decimal equality.")
'''), md(r"""## Current bed layout and its remaining limitations

The plan reader verifies every source STL, the exact part set, project settings,
and checksums of the generated review files. The diagram uses the actual stored
**convex footprint** of each placed mesh; hollow rings and concave pockets remain
filled in this conservative model. Profile-specific settings isolate plates. The
area percentage measures projected hull occupation only and is not a print-time,
filament-use or global packing-optimality claim.

Dashed process halos reserve space; actual supports and brims can still differ.
Layer-by-layer printing is required on multiple-object beds. Nozzle installation,
material calibration, bed adhesion and a full sliced-toolpath inspection remain
separate decisions. A final bed review does not authorize a physical print start.
"""), code('''from uavdesign.printing.project import PrintProject
from matplotlib.patches import Polygon
project = PrintProject(REPO_ROOT)
plan = None
if manifest is not None:
    try:
        plan = project.read_plan()
    except (ValueError, FileNotFoundError) as error:
        print("Current print-plan evidence unavailable:", error)
        print("Regenerate offline with: python -m uavdesign.printing plan")
if plan is not None:
    print("Plan identity:", project.plan_id(), "State:", plan["artifact_state"], "Sliced:", plan["sliced"])
    print("Packing method:", plan["optimization"])
    bed_x, bed_y, bed_z = plan["project"]["printer"]["bed_mm"]
    layout = plan["project"]["layout"]
    print("Required process halo per side [mm]:", layout["process_clearance_mm"])
    print("Additional inter-part gap [mm]:", layout["part_spacing_mm"])
    plate_rows = []
    columns = 3
    rows = int(np.ceil(len(plan["plates"])/columns))
    fig, axes = plt.subplots(rows, columns, figsize=(12, rows*3.5), squeeze=False)
    for ax, plate in zip(axes.flat, plan["plates"]):
        occupied = 0.0
        for index, placement in enumerate(plate["placements"]):
            xy = np.asarray(placement["placed_polygon_mm"])
            halo = np.asarray(placement["reserved_polygon_mm"])
            occupied += .5*abs(np.dot(xy[:,0], np.roll(xy[:,1], 1))-np.dot(xy[:,1], np.roll(xy[:,0], 1)))
            ax.add_patch(Polygon(halo, fill=False, linestyle="--", edgecolor=".65", linewidth=.65))
            ax.add_patch(Polygon(xy, facecolor=f"C{index%10}", alpha=.6, edgecolor=".2", linewidth=.6))
            centre = xy.mean(axis=0)
            ax.text(*centre, str(index+1), ha="center", va="center", fontsize=8)
        ax.set(xlim=(0,bed_x), ylim=(0,bed_y), aspect="equal", title=f"{plate['id']} · {plate['profile']}")
        ax.set_xlabel("x [mm]"); ax.set_ylabel("y [mm]")
        plate_rows.append({"bed":plate["id"], "profile":plate["profile"], "part_count":len(plate["placements"]),
                           "projected_hull_occupation_percent":100*occupied/(bed_x*bed_y),
                           "parts_in_number_order":", ".join(p["part"] for p in plate["placements"])})
    for ax in list(axes.flat)[len(plan["plates"]):]: ax.set_visible(False)
    save(fig, "10_print_bed_atlas.png")
    display(pd.DataFrame(plate_rows))
    print("Unvalidated manufacturing items:")
    for item in plan["outstanding_validation"]: print("-", item)
'''), md(r"""## External-agent review protocol

1. Record the dossier/source revision, notebook execution status and manifest
   hashes. Reproduce equations in notebooks 01, 03, 04 and 09 from the YAML;
   distinguish shared-assumption agreement from independent evidence.
2. Inspect assembly views and STEP, then connect each issue to a named part,
   source key, model function and observable result. Print coordinates are not
   aircraft coordinates; verify datums before comparing dimensions.
3. Review load path, trim at realizable CG, launch thrust, wind/imaging limits,
   rail transients, thermal path and capture timing. Numerical convergence,
   successful tessellation and a valid JSON handoff do not close these issues.
4. Treat missing measured polar, material coupons, joined-structure tests,
   motor/propeller curves, installed harness tests, scale/balance measurements,
   calibration and flight/survey trials as missing evidence. Do not manufacture
   test results to complete a review.
5. Return findings with: **severity; assertion; file/key or part; calculation or
   reproduction command; evidence; proposed change; and acceptance test**.
   Separate a documentation correction, model defect and physical design change.
   Prefer a small reproducible counterexample over an untraceable recommendation.

This notebook intentionally performs no procurement, flight-plan deployment,
printer upload or print start. The user's approval is required before starting
any print; the exported layouts are the artifact to review first.
""")]

NOTEBOOKS = {
    "01_requirements_and_payload.ipynb": NB01,
    "02_airfoil_selection.ipynb": NB02,
    "03_sizing_closure.ipynb": NB03,
    "04_stability_and_trim.ipynb": NB04,
    "05_performance.ipynb": NB05,
    "06_structures.ipynb": NB06,
    "07_fabrication.ipynb": NB07,
    "08_electronics.ipynb": NB08,
    "09_mission_and_balance_sensitivity.ipynb": NB09,
    "10_manufacturing_and_review_audit.ipynb": NB10,
}
