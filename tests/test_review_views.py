"""Evidence integrity and CAD dimension regressions for reviewer drawings."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from uavdesign.fab.review_views import _checked_sources, _hardware_envelopes


def _inputs(tmp_path, step=b'placeholder STEP bytes'):
    parts=tmp_path/'parts'
    (parts/'step').mkdir(parents=True)
    (parts/'step/example.step').write_bytes(step)
    balance=dict(auw_g=3000,cg_x_mm=120,x_np_mm=160,battery_x_mm=10,battery_z_mm=-20,battery_bay='forward')
    geometry=dict(root_chord_mm=300,tip_chord_mm=150,half_span_mm=1000)
    manifest=dict(parts=[{'part':'example','files':{'step':'step/example.step'}}],balance=balance,design=geometry,
                  file_sha256={'step/example.step':hashlib.sha256(step).hexdigest()},payload_config='orin')
    summary=dict(balance=balance,geometry=geometry)
    (parts/'manifest.json').write_text(json.dumps(manifest))
    summary_path=tmp_path/'summary.json'
    summary_path.write_text(json.dumps(summary))
    return parts,summary_path,manifest,summary


def test_review_sources_reject_modified_step(tmp_path):
    parts,summary_path,_,_=_inputs(tmp_path)
    _,_,sources=_checked_sources(parts,summary_path)
    assert set(sources)=={'mechanical/manifest.json','mechanical/step/example.step','design_summary.json'}
    (parts/'step/example.step').write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum mismatch'):
        _checked_sources(parts,summary_path)


def test_review_sources_reject_mixed_design_and_escaping_step(tmp_path):
    parts,summary_path,manifest,summary=_inputs(tmp_path)
    summary['balance']['cg_x_mm']+=3
    summary_path.write_text(json.dumps(summary))
    with pytest.raises(ValueError,match='balance differ'):
        _checked_sources(parts,summary_path)
    manifest['parts'][0]['files']['step']='../../elsewhere.step'
    (parts/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='STEP source must match'):
        _checked_sources(parts,summary_path)


def test_optional_hardware_never_falls_back_to_live_repository(tmp_path):
    parts,summary_path,_,summary=_inputs(tmp_path)
    sources={}
    assert _hardware_envelopes(summary_path,summary,sources)==[]
    assert sources=={}


@pytest.mark.cad
def test_brep_dimensions_ignore_cached_coarse_tessellation():
    import cadquery as cq
    from uavdesign.fab.review_views import _brep_bounds
    shape=cq.Solid.makeSphere(41,cq.Vector(17,-23,9),angleDegrees1=-90,angleDegrees2=90)
    before=_brep_bounds(shape)
    shape.tessellate(8,.6)
    after=_brep_bounds(shape)
    assert np.allclose(before,after,atol=1e-7)
    assert np.allclose(after[1]-after[0],[82,82,82],atol=1e-5)
    assert np.allclose((after[0]+after[1])/2,[17,-23,9],atol=1e-5)


@pytest.mark.cad
def test_drawing_manifest_covers_actual_part_set_and_saved_images(tmp_path):
    import cadquery as cq
    from uavdesign.fab.review_views import export_review_views
    parts,summary_path,manifest,summary=_inputs(tmp_path)
    (parts/'step/example.step').unlink()
    manifest['parts']=[];manifest['file_sha256']={}
    solids=[('wing_seg1_R','wing','wing_skin','R',cq.Solid.makeBox(50,100,5,cq.Vector(0,10,0))),
            ('pod_nose','pod','pod_shell','C',cq.Solid.makeBox(70,20,30,cq.Vector(-20,-10,-15))),
            ('survey_cage','payload','structural','C',cq.Solid.makeBox(10,10,25,cq.Vector(0,-5,-10)))]
    for name,group,profile,side,solid in solids:
        path=parts/f'step/{name}.step'
        cq.exporters.export(solid,str(path))
        relative=str(path.relative_to(parts))
        manifest['file_sha256'][relative]=hashlib.sha256(path.read_bytes()).hexdigest()
        manifest['parts'].append(dict(part=name,group=group,profile=profile,side=side,mass_g=10,files={'step':relative}))
    (parts/'manifest.json').write_text(json.dumps(manifest))
    out=tmp_path/'views'
    result=export_review_views(parts,summary_path,out)
    assert result['part_count']==3
    assert result['hardware_envelopes']==[]
    assert result['dimensions_mm']['x_length']==pytest.approx(70,abs=1e-5)
    assert result['dimensions_mm']['y_span']==pytest.approx(120,abs=1e-5)
    assert result['dimensions_mm']['z_height']==pytest.approx(30,abs=1e-5)
    assert set(result['exploded_offsets_mm'])=={s[0] for s in solids}
    assert not result['tessellation']['dimensions_use_tessellation']
    files={p.name for p in out.iterdir() if p.suffix in ('.png','.svg')}
    assert files==set(result['file_sha256'])
    assert len(result['figures'])==5
    assert json.loads((out/'views_manifest.json').read_text())==result
    for filename,expected in result['file_sha256'].items():
        assert hashlib.sha256((out/filename).read_bytes()).hexdigest()==expected
    with pytest.raises(ValueError,match='separate'):
        export_review_views(parts,summary_path,parts/'pictures')
