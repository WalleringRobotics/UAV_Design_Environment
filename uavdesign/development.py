"""Own-aircraft development checks, explicitly separating models and evidence."""
from __future__ import annotations
import math
from . import design as D
from . import survey
from .aero import stability as st
from .atmosphere import G
from .structures import root_bending_moment_n_mm


def wind_capture_candidates(d):
    """Exposure candidates at the requested tailwind; no camera settings applied."""
    s=d.design['survey'];cam=survey.Camera.from_dict(s['camera'])
    vg=d.selected.cruise_speed_m_s+d.mission['mission']['max_wind_speed_ms']
    rate=survey.trigger_rate_hz(cam,s['agl_m'],vg,s['forward_overlap'])
    cap=min(cam.max_fps,s['acquisition_rate_cap_hz'])
    candidates=sorted(set([s['exposure_s'],.0003,.00025]),reverse=True)
    return dict(groundspeed_m_s=vg,required_capture_hz=rate,acquisition_cap_hz=cap,
                rate_with_20_percent_headroom_pass=rate<=.8*cap,
                minimum_cap_for_20_percent_headroom_hz=rate/.8,
                next_capture_cap_candidate_hz=5.0 if rate/.8<=min(5.0,cam.max_fps) else None,
                max_exposure_s=s['blur_limit_px']*cam.gsd_m(s['agl_m'])/vg,
                candidates=[dict(exposure_s=t,blur_px=survey.blur_px(cam,s['agl_m'],vg,t),
                                 blur_pass=survey.blur_px(cam,s['agl_m'],vg,t)<=s['blur_limit_px'],
                                 image_quality_measured=False) for t in candidates],
                action='Test 0.25 ms image quality; also qualify a higher capture cap or constrain wind/track speed before changing the capture contract')


def attainable_trim(d, balance, config):
    """Trim the unchanged geometry at installed mass/CG; never accept an endpoint."""
    g=D.airframe_geometry(d);p=d.design['planform']
    model=st.WingAeroModel(g['airfoil_root'],g['airfoil_tip'],d.washout_deg,
                          st.ElevonSpec(*g['elevon_y_mm'],1-g['elevon_chord_fraction']),
                          blend_start_mm=g['pod_width_mm']/2)
    rows=[]
    speeds=[d.design['requirements']['hand_launch_speed_m_s'],d.evaluations[config].cruise_speed_m_s,18.0]
    for speed in speeds:
        cl=2*(balance.auw_g/1000)*G/(d.rho*speed**2*d.selected.wing_area_m2)
        try:
            angle,r=st.solve_elevon_trim(d.wing,model,cl,balance.cg_x_mm,
                       pod=(g['pod_length_mm'],g['pod_width_mm']),airspeed_m_s=speed)
            rows.append(dict(airspeed_m_s=speed,cl=cl,elevon_deg=angle,
                             moment_residual=r.cm_at(cl,balance.cg_x_mm),model_trim_found=True))
        except ValueError as exc:
            rows.append(dict(airspeed_m_s=speed,cl=cl,model_trim_found=False,reason=str(exc)))
    return dict(config=config,balance=balance.summary(),cases=rows,flight_validated=False,
                limitation='Linear/inviscid model: stall, combined pitch/roll authority, drag and handling unvalidated')


def launch_voltage_screen(d):
    checks=D.propulsion_checks(d)['checks']
    baseline=next(r for r in checks if r['voltage_state']=='nominal' and r['motor_mass_g']==d.electronics.propulsion_masses_g['motor'])
    v=baseline['voltage_v']*math.sqrt(baseline['required_static_thrust_n']/baseline['static_thrust_n'])
    return dict(selected_method=d.design['requirements']['launch']['selected'],
                modeled_loaded_voltage_for_static_thrust_target_v=v,
                datum='loaded terminal voltage under the assumed RPM model; NOT a launch-permission threshold',
                measured_thrust_curve_available=False,
                full_charge_model_pass=next(r for r in checks if r['candidate']==baseline['candidate'] and r['voltage_state']=='full')['thrust_pass'],
                action='Measure actual thrust/current/RPM/voltage over intended launch pack states; then decide hand versus assisted launch')


def development_report(result):
    from .fab import build as B
    from .fab.geometry import WingGeometry, PodGeometry, spar_layout
    d=result.design;g=D.airframe_geometry(d);w=WingGeometry.from_airframe(g)
    spars=spar_layout(w,g['spars'],g['pod_width_mm']/2)
    pod=PodGeometry.from_dict(result.fab['pod'])
    trims={}
    for config in d.payloads:
        balance=result.balance if config==result.payload_config else B.solve_balance(
            d,result.fab,B.mass_items(d,result.fab,result.parts,w,spars,pod,config))
        trims[config]=attainable_trim(d,balance,config)
    req=d.design['requirements'];weight=result.balance.auw_g/1000*G
    moment=root_bending_moment_n_mm(weight,w.half_span_mm,req['load_factor_limit'],
                                   g['pod_width_mm']/2,d.design['planform']['taper'])
    return dict(schema_version='1.0',program='independent_survey_wing',reference_aircraft_required=False,
                maturity='prototype interfaces and numerical checks; no physical flight qualification',
                attainable_cg_trim=trims,wind_capture_candidates=wind_capture_candidates(d),
                launch=launch_voltage_screen(d),
                structure_load_targets=dict(limit_load_factor=req['load_factor_limit'],safety_factor=req['safety_factor'],
                    total_limit_force_n=weight*req['load_factor_limit'],
                    total_ultimate_force_n=weight*req['load_factor_limit']*req['safety_factor'],
                    root_limit_moment_n_mm=moment,root_ultimate_moment_n_mm=moment*req['safety_factor'],
                    datum='one half-wing at the pod-side root; same Schrenk-like model as tube screen',
                    omitted=['torsion','axial retention','joint peel','buckling','landing impact','fatigue'],
                    assembled_joint_tested=False),
                physical_evidence='See build-improvement register and first-print measurement instructions')
