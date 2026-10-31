from pathlib import Path
import math
import pytest
import yaml
from uavdesign import design as D
from uavdesign.development import wind_capture_candidates,launch_voltage_screen
from uavdesign.fab.geometry import WingGeometry,spar_layout,wing_retention_datums,servo_mount_datums

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def interfaces():
    d=D.run();g=D.airframe_geometry(d)
    f=yaml.safe_load((ROOT/'platforms/survey_wing/fabrication.yaml').read_text())
    w=WingGeometry.from_airframe(g);s=spar_layout(w,g['spars'],g['pod_width_mm']/2)
    r=wing_retention_datums(w,s,f['wing_retention'],g['pod_width_mm']/2)
    return d,g,f,w,s,r

def test_root_fasteners_are_on_opposite_sides_and_clear_carbon(interfaces):
    _,_,_,_,s,r=interfaces
    assert r['bolt_y_mm'][0]<r['root_y_mm']<r['bolt_y_mm'][1]
    assert r['inner_y_mm']<r['bolt_y_mm'][0]<r['bolt_y_mm'][1]<r['outer_y_mm']
    for tube in [s.joiner,s.rear_pin]:
        # Stronger than merely missing a centreline: the whole hardpoint width
        # lies away from the parallel carbon path in this baseline.
        assert abs(r['x_mm']-tube.p0[0])>r['width_mm']/2+tube.od_mm/2
    assert r['anchor_depth_mm']>r['insert_depth_mm']

def test_clamp_fits_nominal_case_and_pilot_has_a_closed_floor(interfaces):
    _,g,f,w,_,_=interfaces
    d=servo_mount_datums(w,f['wing'],g['elevon_y_mm'])
    mount=f['wing']['servo_mount']
    assert d['clamp_z_mm']-mount['insert_depth_mm']>d['floor_z_mm']
    assert d['clamp_z_mm']-d['floor_z_mm']==pytest.approx(10.2)
    assert d['bottom_z_mm']<d['floor_z_mm']<d['clamp_z_mm']<d['top_z_mm']

def test_shutter_fix_does_not_hide_capture_headroom_shortfall(interfaces):
    d,*_=interfaces;r=wind_capture_candidates(d)
    assert r['groundspeed_m_s']>d.survey_speed_limit_m_s
    old=next(x for x in r['candidates'] if x['exposure_s']==.0004)
    fast=next(x for x in r['candidates'] if x['exposure_s']==.00025)
    assert not old['blur_pass'] and fast['blur_pass']
    assert r['required_capture_hz']<r['acquisition_cap_hz']
    assert not r['rate_with_20_percent_headroom_pass']
    assert r['minimum_cap_for_20_percent_headroom_hz']>4
    assert all(not c['image_quality_measured'] for c in r['candidates'])

def test_launch_screen_is_loaded_voltage_and_not_a_measurement(interfaces):
    d,*_=interfaces;r=launch_voltage_screen(d)
    assert d.electronics.pack.nominal_v<r['modeled_loaded_voltage_for_static_thrust_target_v']<d.electronics.pack.max_v
    assert r['selected_method']=='hand'
    assert r['full_charge_model_pass']
    assert not r['measured_thrust_curve_available']

@pytest.mark.cad
def test_prototype_interfaces_are_valid_and_clamp_is_separate(interfaces):
    from uavdesign.fab.parts import build_wing_retention,build_servo_mount,cylinder,box
    from uavdesign.fab.massprops import volume_props
    _,g,f,w,_,r=interfaces
    root=build_wing_retention(w,r)
    tray,clamp=build_servo_mount(w,f['wing'],g['elevon_y_mm'])
    for p in root+[tray,clamp]:
        assert p.solid.isValid() and len(p.solid.Solids())==1
    assert volume_props(tray.solid.intersect(clamp.solid))[0]<1e-5
    assert volume_props(root[0].solid.intersect(root[1].solid))[0]<1e-5
    assert volume_props(root[1].solid.intersect(root[2].solid))[0]<1e-5
    d=servo_mount_datums(w,f['wing'],g['elevon_y_mm'])
    # A representative case envelope has floor contact but no material collision.
    case=box(d['x_mm']-11.9,d['x_mm']+11.9,d['y_mm']-11.25,d['y_mm']+11.25,
             d['floor_z_mm'],d['floor_z_mm']+10)
    assert volume_props(case.intersect(tray.solid))[0]<1e-5
    assert volume_props(case.intersect(clamp.solid))[0]<1e-5

@pytest.mark.cad
def test_coupon_bores_have_the_labelled_diametral_clearance():
    from uavdesign.fab.coupons import bore_gauge,insert_gauge
    s=bore_gauge(14)
    assert s.isValid() and len(s.Solids())==1
    # Last station is +0.6 diameter: clear at r=7.25, solid beyond r=7.3.
    x=2.5+6.5*21
    assert not s.isInside((x+7.25,11,6))
    assert s.isInside((x+7.6,11,6))
    ins=insert_gauge()
    assert ins.isValid() and len(ins.Solids())==1
    assert not ins.isInside((40+2.4,8,8))
    assert ins.isInside((40+2.7,8,8))


@pytest.mark.cad
def test_exported_interfaces_do_not_collide_with_wing_pod_or_cover():
    """Inspect actual serialized STEP geometry, not only separate builder solids."""
    import cadquery as cq
    import json
    from uavdesign.fab.massprops import volume_props
    folder=ROOT/'outputs/parts'
    if not (folder/'manifest.json').is_file():
        pytest.skip('Generate current parts before the exported assembly fit check')
    m=json.loads((folder/'manifest.json').read_text())
    names=[r['part'] for r in m['parts']]
    assert 'wing_root_bridge_R' in names,'Stale aircraft export: rebuild revised parts'
    cache={}
    def shape(name):
        if name not in cache:cache[name]=cq.importers.importStep(str(folder/'step'/f'{name}.step')).val()
        return cache[name]
    def overlaps(a,b):
        x,y=a.BoundingBox(),b.BoundingBox()
        return all(min(getattr(x,k+'max'),getattr(y,k+'max'))>
                   max(getattr(x,k+'min'),getattr(y,k+'min'))+1e-5 for k in 'xyz')
    for side in ['L','R']:
        targets=[n for n in names if n.startswith('wing_seg') and f'_{side}' in n]
        targets+=['pod_nose','pod_mid','pod_tail',f'servo_cover_{side}']
        for stem in ['pod_root_anchor','wing_root_anchor','wing_root_bridge','servo_tray','servo_clamp']:
            part=shape(f'{stem}_{side}')
            for name in targets:
                other=shape(name)
                if overlaps(part,other):
                    assert volume_props(part.intersect(other))[0]<1e-4,(stem,side,name)
